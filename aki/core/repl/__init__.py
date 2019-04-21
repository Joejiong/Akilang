from llvmlite import ir, binding

import colorama

colorama.init()
CMD = colorama.Fore.YELLOW
REP = colorama.Fore.WHITE

RED = colorama.Fore.RED
XX = colorama.Fore.RESET

GRN = colorama.Fore.GREEN
MAG = colorama.Fore.MAGENTA


class Comment(ir.values.Value):
    def __init__(self, parent, text):
        self.text = text

    def __repr__(self):
        return f"; {self.text}"


ir.instructions.Comment = Comment


def comment(self, txt):
    self._insert(ir.instructions.Comment(self.block, txt))


class Timer:
    def __init__(self):
        import time

        self.clock = time.clock

    def __enter__(self):
        self.begin = self.clock()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.end = self.clock()
        self.time = self.end - self.begin


ir.builder.IRBuilder.comment = comment

import ctypes
import os

from core.lex import _AkiLexer as AkiLexer
from core.parse import _AkiParser as AkiParser
from core.codegen import AkiCodeGen
from core.compiler import AkiCompiler, ir
from core.astree import (
    Function,
    Call,
    Prototype,
    ExpressionBlock,
    TopLevel,
    Name,
    VarTypeName,
)
from core.error import AkiBaseErr, ReloadException, QuitException, LocalException
from core.akitypes import AkiTypeMgr, AkiObject
from core import constants


PROMPT = "A>"

USAGE = f"""From the {PROMPT} prompt, type Aki code or enter special commands
preceded by a dot sign:

    {CMD}.about|ab{REP}     : About this program.
    {CMD}.compile|cp{REP}   : Compile current module to executable.
    {CMD}.dump|dp <funcname>{REP}
                  : Dump current module IR to console.
                  : Add <funcname> to dump IR for a function.
    {CMD}.exit|quit|stop|q{REP}
                  : Stop and exit the program.
    {CMD}.export|ex <filename>{REP}
                  : Dump current module to file in LLVM assembler format.
                  : Uses output.ll in current directory as default filename.
    {CMD}.help|.?|.{REP}    : Show this message.
    {CMD}.rerun|..{REP}     : Reload the Python code and restart the REPL. 
    {CMD}.rl[c|r]{REP}      : Reset the interpreting engine and reload the last .aki
                    file loaded in the REPL. Add c to run .cp afterwards.
                    Add r to run main() afterwards.
    {CMD}.reset|~{REP}      : Reset the interpreting engine.
    {CMD}.run|r{REP}        : Run the main() function (if present) in the current
                    module.
    {CMD}.test|t{REP}       : Run unit tests.
    {CMD}.version|ver|v{REP}
                  : Print version information.
    {CMD}.<file>.{REP}      : Load <file>.aki from the src directory.
                    For instance, .l. will load the Conway's Life demo.

These commands are also available directly from the command line, for example: 

    {CMD}aki 2 + 3
    aki test
    aki .myfile.aki{REP}
    
On the command line, the initial dot sign can be replaced with a double dash: 
    
    {CMD}aki --test
    aki --myfile.aki{REP}
"""


class JIT:
    lexer = AkiLexer
    parser = AkiParser

    def __init__(self, typemgr=None, module_name=None):
        if typemgr is None:
            self.typemgr = AkiTypeMgr()
        else:
            self.typemgr = typemgr
        self.types = self.typemgr.types
        self.anon_counter = 0
        self.module_name = module_name
        self.reset()

    def reset(self, typemgr=None):
        if not typemgr:
            typemgr = self.typemgr
        typemgr.reset()
        self.compiler = AkiCompiler()
        self.module = ir.Module(self.module_name)
        self.module.triple = binding.Target.from_default_triple().triple
        self.codegen = AkiCodeGen(self.module, self.typemgr)


def cp(string):
    print(f"{REP}{string}")


class Repl:

    import sys

    VERSION = f"""Python :{sys.version}
LLVM   :{".".join((str(n) for n in binding.llvm_version_info))}
pyaki  :{constants.VERSION}"""

    def __init__(self, typemgr=None):
        self.reset(silent=True, typemgr=typemgr)

    def run_tests(self, *a):
        print(f"{REP}", end="")
        import unittest

        tests = unittest.defaultTestLoader.discover("tests", "*.py")
        unittest.TextTestRunner().run(tests)

    def load_file(self, file_to_load, ignore_cache=False):

        self.main_cpl.reset(typemgr=self.typemgr)

        # Attempt to load precomputed module from cache

        file_dir = "examples"

        filepath = f"{file_dir}/{file_to_load}.aki"

        if not ignore_cache:

            force_recompilation = False

            cache_path = f"{file_dir}/__akic__/"
            cache_file = f"{file_to_load}.akic"
            full_cache_path = cache_path + cache_file

            if not os.path.exists(full_cache_path):
                force_recompilation = True
            elif os.path.getmtime(filepath) > os.path.getmtime(full_cache_path):
                force_recompilation = True

            if not force_recompilation:
                try:
                    with Timer() as t:
                        with open(full_cache_path, "rb") as file:
                            import pickle

                            mod_in = pickle.load(file)
                            if mod_in["version"] != constants.VERSION:
                                raise LocalException
                            self.main_cpl.codegen = mod_in["codegen"]
                            self.main_cpl.compiler.compile_bc(mod_in["bitcode"])
                            self.typemgr = self.main_cpl.codegen.typemgr
                            file_size = os.fstat(file.fileno()).st_size

                    cp(
                        f"Read {file_size} bytes from {CMD}{cache_file}{REP} ({t.time:.3f} sec)"
                    )
                    return
                except LocalException:
                    pass
                except Exception:
                    cp(f"Error reading cached file")

        with Timer() as t:

            try:
                with open(filepath) as file:
                    text = file.read()
                    file_size = os.fstat(file.fileno()).st_size
            except FileNotFoundError:
                raise AkiBaseErr(
                    None, file_to_load, f"File not found: {CMD}{filepath}{REP}"
                )

            tokens = self.main_cpl.lexer.tokenize(text)
            ast = self.main_cpl.parser.parse(tokens, text)

            self.main_cpl.codegen.text = text
            self.main_cpl.codegen.eval(ast)
            self.main_cpl.compiler.compile_module(self.main_cpl.module, file_to_load)

        # Write cached compilation to file

        if not ignore_cache:

            try:
                if not os.path.exists(cache_path):
                    os.makedirs(cache_path)
                with open(full_cache_path, "wb") as file:
                    output = {
                        "version": constants.VERSION,
                        "bitcode": self.main_cpl.compiler.mod_ref.as_bitcode(),
                        "codegen": self.main_cpl.codegen,
                    }
                    import pickle

                    try:
                        pickle.dump(output, file)
                    except Exception:
                        raise LocalException
            except LocalException:
                cp("Can't write bytecode")
                os.remove(cache_path)

        cp(f"Read {file_size} bytes from {CMD}{filepath}{REP} ({t.time:.3f} sec)")

    def quit(self, *a):
        print(XX)
        raise QuitException

    def reload(self, *a):
        print(XX)
        raise ReloadException

    def run(self):
        import shutil

        cols = shutil.get_terminal_size()[0]
        if cols < 80:
            warn = f"\n{RED}Terminal is less than 80 colums wide.\nOutput may not be correctly formatted."
        else:
            warn = ""

        cp(
            f"{GRN}{constants.WELCOME}{warn}\n{REP}Type {CMD}.help{REP} or a command to be interpreted"
        )
        while True:
            try:
                print(f"{REP}{PROMPT}{CMD}", end="")
                text = input()
                self.cmd(text)
            except AkiBaseErr as e:
                print(e)
            except EOFError:
                break

    def help(self, *a):
        cp(f"\n{USAGE}")

    def cmd(self, text):
        if not text:
            return
        if text[0] == ".":
            if len(text) == 1:
                self.help()
                return
            if text[-1] == ".":
                if len(text) == 2:
                    return self.reload()
                text = text[1:-1]
                self.load_file(text)
                return
            command = text[1:]
        else:
            print(f"{REP}", end="")
            for _ in self.interactive(text):
                print(_)
            return

        cmd_func = self.cmds.get(command, None)

        if cmd_func is None:
            cp(f'Unrecognized command "{CMD}{command}{REP}"')
            return

        return cmd_func(self, text)

    def interactive(self, text, immediate_mode=False):
        # Immediate mode processes everything in the repl compiler.
        # Nothing is retained.

        if immediate_mode:
            main = self.repl_cpl
            main_file = None
            repl_file = None
        else:
            main = self.main_cpl
            main_file = "main"
            repl_file = "repl"

        self.repl_cpl.reset()

        # Tokenize input

        tokens = self.repl_cpl.lexer.tokenize(text)
        ast = self.repl_cpl.parser.parse(tokens, text)

        # Iterate through tokens

        self.repl_cpl.codegen.text = text
        main.codegen.text = text

        # Iterate through the AST nodes.
        # When we encounter an expression node,
        # we add it to a stack of expression nodes.
        # When we encounter a top-level command,
        # we compile it immediately, and don't add it
        # to the stack.

        ast_stack = []

        for _ in ast:

            if isinstance(_, TopLevel):
                main.codegen.eval([_])
                main.compiler.compile_module(main.module, main_file)
                continue

            ast_stack.append(_)

        # When we come to the end of the node list,
        # we take the expression node stack, turn it into
        # an anonymous function, and execute it.

        if ast_stack:

            res, return_type = self.anonymous_function(
                ast_stack, repl_file, immediate_mode
            )

            yield return_type.format_result(res)

    def anonymous_function(self, ast_stack, repl_file, immediate_mode=False):

        _ = ast_stack[-1]

        self.repl_cpl.anon_counter += 1

        call_name = f"_ANONYMOUS_{self.repl_cpl.anon_counter}"
        proto = Prototype(_.p, call_name, (), VarTypeName(_.p, None))
        func = Function(_.p, proto, ExpressionBlock(_.p, ast_stack))

        if not immediate_mode:
            self.repl_cpl.codegen.other_modules.append(self.main_cpl.codegen)

        try:
            self.repl_cpl.codegen.eval([func])
        except AkiBaseErr as e:
            del self.repl_cpl.module.globals[call_name]
            raise e

        first_result_type = self.repl_cpl.module.globals[call_name].return_value.akitype

        # If the result from the codegen is an object,
        # redo the codegen with an addition to the AST stack
        # that extracts the c_data value.

        if isinstance(first_result_type, AkiObject):
            _ = ast_stack.pop()
            ast_stack = []

            ast_stack.append(
                Call(
                    _.p,
                    "c_data",
                    (Call(_.p, call_name, (), VarTypeName(_.p, None)),),
                    VarTypeName(_.p, None),
                )
            )

            call_name += "_WRAP"
            proto = Prototype(_.p, call_name, (), VarTypeName(_.p, None))
            func = Function(_.p, proto, ExpressionBlock(_.p, ast_stack))

            # It's unlikely that this codegen will ever throw an error,
            # but I'm keeping this anyway

            try:
                self.repl_cpl.codegen.eval([func])
            except AkiBaseErr as e:
                del self.repl_cpl.module.globals[call_name]
                raise e

            final_result_type = self.repl_cpl.module.globals[
                call_name
            ].return_value.akitype

        else:
            final_result_type = first_result_type

        if not immediate_mode:
            if self.main_cpl.compiler.mod_ref:
                self.repl_cpl.compiler.backing_mod.link_in(
                    self.main_cpl.compiler.mod_ref, True
                )

        self.repl_cpl.compiler.compile_module(self.repl_cpl.module, repl_file)

        # Retrieve a pointer to the function
        func_ptr = self.repl_cpl.compiler.get_addr(call_name)

        return_type = first_result_type
        return_type_ctype = final_result_type.c()

        # Get the function signature
        func_signature = [
            _.aki.vartype.aki_type.c()
            for _ in self.repl_cpl.module.globals[call_name].args
        ]

        # Generate a result
        cfunc = ctypes.CFUNCTYPE(return_type_ctype, *[])(func_ptr)
        res = cfunc()

        return res, return_type

    def about(self, *a):
        print(f"\n{GRN}{constants.ABOUT}\n\n{self.VERSION}\n")

    def not_implemented(self, *a):
        cp(f"{RED}Not implemented yet")

    def version(self, *a):
        print(f"\n{GRN}{self.VERSION}\n")

    def load_test(self, *a):
        self.load_file("1")

    def reset(self, *a, **ka):
        if "typemgr" not in ka or ka["typemgr"] is None:
            self.typemgr = AkiTypeMgr()
        else:
            self.typemgr = ka["typemgr"]
            self.typemgr.reset()
        self.types = self.typemgr.types
        self.main_cpl = JIT(self.typemgr, module_name=".main")
        self.repl_cpl = JIT(self.typemgr, module_name=".repl")
        if not "silent" in ka:
            cp(f"{RED}Workspace reset")

    cmds = {
        "t": run_tests,
        "l": load_test,
        "q": quit,
        ".": reload,
        "ab": about,
        "about": about,
        "compile": not_implemented,
        "cp": not_implemented,
        "dump": not_implemented,
        "dp": not_implemented,
        "exit": quit,
        "quit": quit,
        "stop": quit,
        "q": quit,
        "export": not_implemented,
        "ex": not_implemented,
        "help": help,
        "?": help,
        "rerun": not_implemented,
        "rl": not_implemented,
        "rlc": not_implemented,
        "rlr": not_implemented,
        "reset": reset,
        "~": reset,
        "run": not_implemented,
        "r": not_implemented,
        "test": run_tests,
        "version": version,
        "ver": version,
        "v": version,
    }

