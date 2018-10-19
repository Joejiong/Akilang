from core.llvmlite_custom import Map, _PointerType, MyType
from core.tokens import Dunders

import llvmlite.ir as ir
import ctypes
from llvmlite import binding

# Singleton types (these do not require an invocation, they're only created once)

def make_type_as_ptr(my_type):
    def type_as_ptr(addrspace=0):
        t = _PointerType(my_type, addrspace, v_id=my_type.v_id)
        return t

    return type_as_ptr


class Bool(ir.IntType):
    p_fmt = '%i'

    def __new__(cls):
        return super().__new__(cls, 1, False, True)


class SignedInt(ir.IntType):
    p_fmt = '%i'

    def __new__(cls, bits, force=True):
        return super().__new__(cls, bits, force, True)


class UnsignedInt(ir.IntType):
    p_fmt = '%u'

    def __new__(cls, bits, force=True):
        return super().__new__(cls, bits, force, False)


class Float32(ir.FloatType):
    def __new__(cls):
        t = super().__new__(cls)
        t.signed = True
        t.v_id = 'f32'
        t.width = 32
        t.is_obj = False
        t.p_fmt = '%f'
        return t

class Float64(ir.DoubleType):
    def __new__(cls):
        t = super().__new__(cls)
        t.signed = True
        t.v_id = 'f64'
        t.width = 64
        t.is_obj = False
        t.p_fmt = '%f'
        return t


ir.IntType.is_obj = False


class Array(ir.ArrayType):
    is_obj = False

    def __init__(self, my_type, my_len):
        super().__init__(my_type, my_len)
        self.v_id = 'array_' + my_type.v_id
        self.signed = my_type.signed
        self.as_pointer = make_type_as_ptr(self)

class CustomClass():
    def __new__(cls, name, types, v_types):
        new_class = ir.global_context.get_identified_type('.class.' + name)
        new_class.elements = types
        new_class.v_types = v_types
        new_class.v_id = name
        new_class.signed = False
        new_class.is_obj = True
        new_class.as_pointer = make_type_as_ptr(new_class)
        return new_class


class ArrayClass(ir.types.LiteralStructType):
    '''
    Type for arrays whose dimensions are defined at compile time.
    '''
    is_obj = True

    def __init__(self, my_type, elements):
        
        arr_type = my_type
        for n in reversed(elements):
            arr_type = VarTypes.array(arr_type, n)

        master_type = [
                VarTypes._header,
                arr_type
            ]
            
        super().__init__(
            master_type
        )

        self.v_id = f'array_{my_type.v_id}'
        self.del_id = 'array'
        self.del_as_ptr = True
        self.as_pointer = make_type_as_ptr(self)
        self.master_type = master_type
        self.arr_type = my_type
    
    def new_signature(self):
        return (
            '.object.array.__new__',
            self.arr_type
        )
    
    def post_new_bitcast(self, builder, obj):
        obj = builder.bitcast(
            obj,
            self.as_pointer()
        )

        return obj

# boxing of types:
# later, we'll create a structure of elements
# each element position is a type
# the ID for the box object will point to that type
# for custom types, we just add them to that struct for each module

_default_platform_module = ir.Module()
_default_platform_vartypes = {_default_platform_module.triple:None}

def generate_vartypes(module=None, bytesize=8):

    # if no module, assume current platform
    # cache a copy of the default platform module
    # for the lifetime of the app

    if module is None:
        module = _default_platform_module

    if  _default_platform_vartypes.get(module.triple, None) is not None:
        return _default_platform_vartypes[module.triple]

    # Initialize target data for the module.
    target_data = binding.create_target_data(module.data_layout)

    # Set up pointer size and u_size vartype for current hardware.
    _byte_width = (
        ir.PointerType(ir.IntType(bytesize)).get_abi_size(target_data)
    )

    _pointer_width = _byte_width * bytesize

    U_MEM = UnsignedInt(_byte_width)
    U_SIZE = UnsignedInt(_pointer_width)

    # create universal object header
    # the first element in this structure:

    # [[1,2,3][4]]
    # 1: length of data element
    # 2: is_external for data: 1=yes, it's externally stored, see pointer, needs separate dealloc
    # 3: pointer to data (if stored externally)
    # 4: actual object data (if any)    

    Header = ir.global_context.get_identified_type('.object_header.')
    Header.elements = (
        # total length of data element in bytes as u64
        U_SIZE,
        # pointer to object data
        U_MEM.as_pointer(), # generic ptr void

        # object refcount
        U_SIZE,
        
        # flag for whether or not pointed-to obj (by way of element 1) is dynamically allocated (bool)
        # default is 0
        ir.IntType(1),

        # flag for whether or not this obj is dynam. alloc.
        # default is also 0
        ir.IntType(1),

    )

    Header.packed = True

    # for arrays at compile time, we can encode the dimensions at compile time
    # and any calls will be optimized out to constants anyway
    # need to see if the .initializer property works for runtime

    # Result type

    Result = ir.global_context.get_identified_type('.result.')
    Result.elements = (
        # OK or err?
        ir.IntType(1),
        # if false
        ir.IntType(_byte_width).as_pointer(),
        # if true
        ir.IntType(_byte_width).as_pointer(),
    )

    # ? should result type be treated as an object w/header?

    # when we compile,
    # we bitcast the ptr to #1 to the appropriate object type
    # based on what we expect
    # for instance, if we have a function that returns an i64
    # but can throw an exception,
    # then any results returned from that have element 1 bitcast
    # as a pointer to an i64 somewhere (malloc'd)
    # it may be possible to return the data directly inside the structure
    # depending on how funky we want to get...
    # basically, we generate the result structure on the fly each time?


    # create objects dependent on the ABI size

    Str = ir.global_context.get_identified_type('.object.str')
    Str.elements = (Header,) 
    Str.v_id = 'str'
    Str.is_obj = True
    Str.signed = False
    Str.ext_ptr = UnsignedInt(8, True).as_pointer()
    Str.p_fmt = '%s'
    Str.as_pointer = make_type_as_ptr(Str)

    _vartypes = Map({

        # singleton
        'u1': Bool(),
        'i8': SignedInt(8),
        'i16': SignedInt(16),
        'i32': SignedInt(32),
        'i64': SignedInt(64),
        'u8': UnsignedInt(8),
        'u16': UnsignedInt(16),
        'u32': UnsignedInt(32),
        'u64': UnsignedInt(64),
        'f32': Float32(),
        'f64': Float64(),

        # u_size is set on init
        'u_size': None,

        # non-singleton        
        'array': Array,
        'func': ir.FunctionType,

        # object types
        'str': Str,

    })

    _vartypes._header = Header

    # set platform-dependent sizes
    _vartypes._byte_width = _byte_width
    _vartypes._pointer_width = _pointer_width
    
    _vartypes['u_size'] = UnsignedInt(_vartypes._pointer_width)
    _vartypes['u_mem'] = UnsignedInt(_vartypes._byte_width)

    # add these types in manually, since they just shadow existing ones
    _vartypes['bool'] = _vartypes.u1
    _vartypes['byte'] = _vartypes.u8

    # TODO: this should be moved back into the underlying types?
    _vartypes.f32.c_type = ctypes.c_double
    _vartypes.f64.c_type = ctypes.c_longdouble

    _vartypes.func.is_obj = True

    # set defaults for functions and variables
    _vartypes._DEFAULT_TYPE = _vartypes.i32
    _vartypes._DEFAULT_RETURN_VALUE = ir.Constant(_vartypes.i32, 0)

    # set the target data reference
    _vartypes._target_data = target_data

    # box_id - possibly to be used for boxing and unboxing types
    for _, n in enumerate(_vartypes):
        if not n.startswith('_'):
            _vartypes[n].box_id = _
    
    _default_platform_vartypes[module.triple] = _vartypes
    return _vartypes

VarTypes = generate_vartypes()

DEFAULT_TYPE = VarTypes._DEFAULT_TYPE
DEFAULT_RETURN_VALUE = VarTypes.DEFAULT_RETURN_VALUE

dunder_methods = set([f'__{n}__' for n in Dunders])

Str = VarTypes.str

