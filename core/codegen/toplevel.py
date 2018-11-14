from core.ast_module import _ANONYMOUS, Binary, Variable, String, Number, Global, ItemList
import llvmlite.ir as ir
from core.mangling import mangle_call, mangle_args, mangle_types, mangle_optional_args, MANGLE_SEPARATOR
from core.errors import CodegenError, CodegenWarning
from core.tokens import decorator_collisions

# pylint: disable=E1101


class Toplevel():

    def _codegen_Pragma(self, node):
        '''
        Iterate through a `pragma` block and register each
        name/value pair with the module's metadata.
        '''

        # At some point we'll just make this into an extension of
        # `const`, but I think we need special processing for now
        # esp. since I'd like to find a more elegant way of dealing
        # w/finding existing vars in a subeval, maybe by way of
        # passing it the current eval as a parameter?

        e = self.init_evaluator()

        for n in node.pragmas:
            if not isinstance(n, Binary):
                raise CodegenError(
                    'Invalid "pragma" declaration (must be in the format "<identifier> = <value>")',
                    n.position
                )

            if isinstance(n.rhs, Variable):
                val = e.eval_and_return(n.rhs).value

            # an inline string literal doesn't need to be evaled
            elif isinstance(n.rhs, String):
                val = n.rhs.val

            # ditto numbers, integers only tho
            elif isinstance(n.rhs, Number):
                try:
                    val = int(n.rhs.val)
                except:
                    raise CodegenError(
                        'Invalid "pragma" declaration (value must be a string or integer)',
                        n.rhs.position
                    )

            else:
                raise CodegenError(
                    'Invalid "pragma" declaration (value must be a string or integer)',
                    n.rhs.position
                )

            self.pragmas[n.lhs.name] = val

    def _codegen_Decorator(self, node):
        '''
        Set the decorator stack and generate the code tagged by the decorator.
        '''

        self.func_decorators.append(node.name)
        for n in node.body:
            _ = self._codegen(n, False)
        self.func_decorators.pop()
        return _

    def _codegen_Class(self, node):
        self.class_symtab[node.name] = node.vartype

    def _codegen_Prototype(self, node):
        funcname = node.name

        # Create a function type

        vartypes = []
        vartypes_with_defaults = []

        append_to = vartypes

        for x in node.argnames:
            s = x.vartype
            if x.initializer is not None:
                append_to = vartypes_with_defaults
            append_to.append(s)

        # TODO: it isn't yet possible to have an implicitly
        # typed function that just uses the return type of the body
        # we might be able to do this by way of a special call
        # to this function
        # note that Extern functions MUST be typed

        if node.vartype is None:
            node.vartype = self.vartypes._DEFAULT_TYPE

        functype = ir.FunctionType(
            node.vartype,
            vartypes+vartypes_with_defaults
        )

        public_name = funcname

        opt_args = None

        linkage = None

        # TODO: identify anonymous functions with a property
        # not by way of their nomenclature

        if node.extern is False and not funcname.startswith('_ANONYMOUS.') and funcname != 'main':
            linkage = 'private'
            if len(vartypes) > 0:
                funcname = public_name + mangle_args(vartypes)
            else:
                funcname = public_name + MANGLE_SEPARATOR

            required_args = funcname

            if len(vartypes_with_defaults) > 0:
                opt_args = mangle_optional_args(vartypes_with_defaults)
                funcname += opt_args

        # If a function with this name already exists in the module...
        if funcname in self.module.globals:

            # We only allow the case in which a declaration exists and now the
            # function is defined (or redeclared) with the same number of args.

            func = existing_func = self.module.globals[funcname]

            if not isinstance(existing_func, ir.Function):
                raise CodegenError(
                    f'Function/universal name collision "{funcname}"',
                    node.position
                )

            # If we're redefining a forward declaration,
            # erase the existing function body

            if not existing_func.is_declaration:
                existing_func.blocks = []

            if len(existing_func.function_type.args) != len(functype.args):
                raise CodegenError(
                    f'Redefinition of function "{public_name}" with different number of arguments',
                    node.position)
        else:
            # Otherwise create a new function

            func = ir.Function(self.module, functype, funcname)

            # Name the arguments
            for i, arg in enumerate(func.args):
                arg.name = node.argnames[i].name

        if opt_args is not None:
            self.opt_args_funcs[required_args] = func

        # Set defaults (if any)

        for x, n in enumerate(node.argnames):
            if n.initializer is not None:
                func.args[x].default_value = self._codegen(
                    n.initializer, False)

        if node.varargs:
            func.ftype.var_arg = True

        func.public_name = public_name

        func.returns = []

        ##############################################################
        # Set LLVM function attributes
        ##############################################################

        # First, extract a copy of the function decorators
        # and use that to set up other attributes

        decorators = [n.name for n in self.func_decorators]

        varfunc = 'varfunc' in decorators

        for a, b in decorator_collisions:
            if a in decorators and b in decorators:
                raise CodegenError(
                    f'Function cannot be decorated with both "@{a}" and "@{b}"',
                    node.position
                )

        # Calling convention.
        # This is the default with no varargs

        if node.varargs is None:
            if not node.extern:
                func.calling_convention = 'fastcc'

        # Linkage.
        # Default is 'private' if it's not extern, an anonymous function, or main

        if linkage:
            func.linkage = linkage

        # Address is not relevant by default
        func.unnamed_addr = True

        # Enable optnone for main() or anything
        # designated as a target for a function pointer.
        if funcname == 'main' or varfunc:
            func.attributes.add('optnone')
            func.attributes.add('noinline')

        # Inlining. Operator functions are inlined by default.

        if (
            # function is manually inlined
            ('inline' in decorators)
            or
            # function is an operator, not @varfunc,
            # and not @noinline
            (node.isoperator and not varfunc and 'noinline' not in decorators)
        ):
            func.attributes.add('alwaysinline')

        # function is @noinline
        # or function is @varfunc
        if 'noinline' in decorators:
            func.attributes.add('noinline')

        # End inlining.

        # External calls, by default, no recursion
        if node.extern:
            func.attributes.add('norecurse')
            func.linkage = 'dllimport'

        # By default, no lazy binding
        func.attributes.add('nonlazybind')

        # By default, no stack unwinding
        func.attributes.add('nounwind')

        func.decorators = decorators

        if 'track' in decorators:
            func.tracked = True

        return func

    def _codegen_Function(self, node):

        # For functions with an empty body,
        # typically a forward declaration,
        # just generate the prototype.
        if not node.body:
            func = self._codegen(node.proto, False)
            return func

        # Reset the symbol table. Prototype generation will pre-populate it with
        # function arguments.
        self.func_symtab = {}

        # Create the function skeleton from the prototype.
        func = self._codegen(node.proto, False)

        # Create the entry BB in the function and set a new builder to it.
        bb_entry = func.append_basic_block('entry')
        self.builder = ir.IRBuilder(bb_entry)

        self.func_incontext = func
        self.func_returncalled = False
        self.func_returntype = func.return_value.type
        self.func_returnblock = func.append_basic_block('exit')
        self.func_returnarg = self._alloca(
            '%_return', self.func_returntype, node=node)

        # Add all arguments to the symbol table and create their allocas
        for _, arg in enumerate(func.args):
            if arg.type.is_obj_ptr():
                alloca = arg
            else:
                alloca = self._alloca(arg.name, arg.type,
                                      node=node.proto.argnames[_])
                self.builder.store(arg, alloca)

            # We don't shadow existing variables names, ever
            assert not self.func_symtab.get(
                arg.name) and "arg name redefined: " + arg.name

            self.func_symtab[arg.name] = alloca

            alloca.input_arg = _
            alloca.tracked = False

        # Generate code for the body
        retval = self._codegen(node.body, False)

        if retval is None and self.func_returncalled is True:
            # we don't need to check for a final returned value,
            # because it's implied that there's an early return
            pass
        else:

            if not hasattr(retval, 'type'):
                raise CodegenError(
                    f'Function "{node.proto.name}" has a return value of type "{func.return_value.type.describe()}" but no concluding expression with an explicit return type was supplied',
                    node.position)

            if retval is None and func.return_value.type is not None:
                raise CodegenError(
                    f'Function "{node.proto.name}" has a return value of type "{func.return_value.type.describe()}" but no expression with an explicit return type was supplied',
                    node.position)

            # We need to have return type compatibility checking
            # performed on a separate instance of the object,
            # otherwise the tracking functions break and
            # the object is incorrectly auto-deleted

            retval2 = self._check_array_return_type_compatibility(
                retval, self.func_returntype
            )

            if func.return_value.type != retval2.type:
                if node.proto.name.startswith(_ANONYMOUS):
                    func.return_value.type = retval.type
                    self.func_returnarg = self._alloca('%_return', retval.type)
                else:
                    raise CodegenError(
                        f'Prototype for function "{node.proto.name}" has return type "{func.return_value.type.describe()}", but returns "{retval.type.describe()}" instead (maybe an implicit return?)',
                        node.proto.position)

            self.builder.store(retval2, self.func_returnarg)
            self.builder.branch(self.func_returnblock)

        self.builder = ir.IRBuilder(self.func_returnblock)

        # Check for the presence of a returned object
        # that requires memory tracing
        # if so, add it to the set of functions that returns a trackable object

        to_check = retval

        if retval:
            to_check = self._extract_operand(retval)
            if to_check.tracked:  # or 'track' in func.decorators:
                self.gives_alloc.add(self.func_returnblock.parent)
                self.func_returnblock.parent.returns.append(to_check)

        # Determine which variables need to be automatically disposed
        # Be sure to exclude anything we return!

        if to_check:
            self._codegen_autodispose(
                reversed(list(self.func_symtab.items())),
                to_check,
                node
            )

        # TODO: if this function throws exceptions,
        # we need to return an object wrapper, not a bare object
        # this requires rewriting the function signature, etc.

        self.builder.ret(self.builder.load(self.func_returnarg))

        self.func_incontext = None
        self.func_returntype = None
        self.func_returnarg = None
        self.func_returnblock = None
        self.func_returncalled = None

    def _codegen_Const(self, node):
        return self._codegen_Uni(node, True)

    # doesn't work yet
    def x_codegen_Uni(self, node, const=False):
        return self._codegen_Var(node, False, const, True)
    
    def _codegen_Uni(self, node, const=False):
        for v in node.vars:
            name = v.name
            expr = v.initializer
            vartype = v.vartype
            position = v.position

            var_ref = self.module.globals.get(name, None)

            if var_ref is not None:
                raise CodegenError(
                    f'Duplicate found in universal symbol table: "{name}"',
                    position)

            if const and expr is None:
                raise CodegenError(
                    f'Constants must have an assignment: "{name}"', position)

            value = None

            # if there is no initializer
            # (this is only valid for uni, not const)
            if expr is None:

                #a and there is no vartype
                if vartype is None:
                    
                    # assume default vartype
                    vartype = self.vartypes._DEFAULT_TYPE
            
            # if there is an initializer
            else:                
                value = self._codegen_create_initializer(
                        None, expr
                    )
                # but no vartype
                if vartype is None:
                    # get the vartype from the initializer                    
                    vartype = value.type
                else:
                    pass
                    

            if value is None:
                if vartype.is_obj_ptr():
                    value = self._codegen(
                        Global(
                            position,
                            ir.Constant(vartype.pointee, None),
                            f"{name}.init",
                            #global_constant=const
                            global_constant=False
                        )
                    )
                    
                else:
                    value = ir.Constant(vartype, None)


            if not isinstance(expr, ItemList):
                variable = self._codegen(
                    Global(position, value, name, const)
                )   
                
            
            else:

                variable=ir.GlobalVariable(self.module,
                    vartype.pointee,
                    name,                    
                )                

                element_count = len(value.initializer.constant)
                array_length = vartype.pointee.elements[1].count

                if array_length == 0:
                    vartype.pointee.elements[1].count = element_count
                    array_length = element_count

                if element_count>array_length:
                    raise CodegenError(
                        f'Array initializer is too long (expected {array_length} elements, got {element_count})',
                        expr.position
                    )

                if element_count<array_length:
                    CodegenWarning(
                        f'Array initializer does not fill entire array; remainder will be zero-filled (array has {array_length} elements; initializer has {element_count})',
                        v.position
                        ).print(self)

                for _ in range(0,array_length-element_count):
                    value.initializer.constant.append(
                        ir.Constant(value.initializer.type.element,
                        None)
                    )
                
                value.initializer.type.count = len(value.initializer.constant)
                
                initializer= ir.Constant(
                    vartype.pointee,
                    [
                        [self.vartypes.u_size(
                            vartype.pointee.elements[1].count
                        ),
                        ir.Constant(
                            self.vartypes.u_mem.as_pointer(),
                            None
                        ),
                        self.vartypes.u_size(0),
                        self.vartypes.bool(0),
                        self.vartypes.bool(0),
                        ],
                        value.initializer
                    ]
                )

                variable.initializer = initializer
                variable.global_constant = const

                # We can in theory delete the initializer by way of
                # del self.module.globals[value.name]
                # but we should keep it in case anything else
                # refers to it.
                # It will be optimized out if nothing uses it.

