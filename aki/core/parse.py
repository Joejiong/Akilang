from sly import Parser
from core.lex import AkiLexer, Pos
from core.astree import (
    Constant,
    String,
    UnOp,
    BinOp,
    BinOpComparison,
    Name,
    Prototype,
    Function,
    External,
    VarList,
    Argument,
    Call,
    ExpressionBlock,
    IfExpr,
    WhenExpr,
    Assignment,
    LoopExpr,
    Break,
    WithExpr,
    VarTypeName,
    VarTypePtr,
    VarTypeFunc,
    RefExpr,
    DerefExpr,
    ChainExpr,
)
from core.error import AkiSyntaxErr


class AkiParser(Parser):
    #debugfile = "parser.out"
    tokens = AkiLexer.tokens
    start = "toplevels"

    class NullLogger:
        warning = lambda *a: None
        info = warning

    log = NullLogger

    precedence = (
        ("right", "ASSIGN"),
        ("right", "UMINUS", "NOT"),
        ("left", "LOOP", "IF", "WHEN", "ELSE"),
        ("left", "AND", "BIN_AND"),
        ("left", "OR", "BIN_OR"),
        ("left", "EQ", "NEQ", "GEQ", "LEQ", "GT", "LT"),
        ("left", "INCR", "DECR"),
        ("left", "PLUS", "MINUS"),
        ("left", "TIMES", "DIV", "INT_DIV"),
    )

    def parse(self, tokens, text):
        self.text = text
        return super().parse(tokens)

    def error(self, p):
        raise AkiSyntaxErr(Pos(p), self.text, "Unrecognized syntax")

    #################################################################
    # toplevel statements
    #################################################################

    @_("toplevels toplevel")
    def toplevels(self, p):
        return p.toplevels + [p.toplevel]

    @_("toplevel")
    def toplevels(self, p):
        return [p.toplevel]

    @_("expr")
    def toplevel(self, p):
        return p.expr

    # semicolon: optional expression separator

    @_("SEMI")
    def expr(self, p):
        return ExpressionBlock(Pos(p), [])

    # `def` function (toplevel)

    @_("DEF NAME arglist optvartype expr_block")
    def toplevel(self, p):
        proto = Prototype(Pos(p), p.NAME, p.arglist, p.optvartype)
        func = Function(Pos(p), proto, p.expr_block)
        return func

    # `extern` function (toplevel)

    @_("EXTERN NAME arglist vartype")
    def toplevel(self, p):
        proto = Prototype(Pos(p), p.NAME, p.arglist, p.vartype)
        func = External(Pos(p), proto, None)
        return func        

    #################################################################
    # Multiline expressions
    #################################################################

    @_("expr")
    def expr_block(self, p):
        return p.expr

    @_("expr_block_d")
    def expr(self, p):
        return p.expr_block_d

    @_("LBRACE empty RBRACE")
    def expr_block_d(self, p):
        return ExpressionBlock(Pos(p), [])

    @_("LBRACE exprset RBRACE")
    def expr_block_d(self, p):
        return ExpressionBlock(Pos(p), p.exprset)

    @_("exprset expr")
    def exprset(self, p):
        return p.exprset + [p.expr]

    @_("expr")
    def exprset(self, p):
        return [p.expr]

    #################################################################
    # Parenthetical expressions
    #################################################################

    @_("LPAREN expr RPAREN")
    def expr(self, p):
        return p.expr

    @_("LPAREN empty RPAREN")
    def expr(self, p):
        return ExpressionBlock(Pos(p), [])

    #################################################################
    # non-top-level statements; expressions
    #################################################################

    # numerals

    @_("INTEGER")
    def expr(self, p):
        return Constant(Pos(p), p.INTEGER, VarTypeName(Pos(p), "i32"))

    @_("FLOAT")
    def expr(self, p):
        return Constant(Pos(p), p.FLOAT, VarTypeName(Pos(p), "f64"))

    # hex value constants

    @_("HEX")
    def expr(self, p):
        if p.HEX[1] == "x":
            # 0x00 = unsigned
            sign = "u"
        else:
            # 0h00 = signed
            sign = "i"
        bytelength = (len(p.HEX[2:])) * 4
        value = int(p.HEX[2:], 16)
        if bytelength < 8:
            if value > 1:
                bytelength = 8
                typestr = f"{sign}{bytelength}"
            else:
                typestr = "bool"
        else:
            typestr = f"{sign}{bytelength}"

        return Constant(Pos(p), value, VarTypeName(Pos(p), typestr))

    # names

    @_("NAME")
    def expr(self, p):
        return Name(Pos(p), p.NAME)

    # string constants

    @_("TEXT1", "TEXT2")
    def expr(self, p):
        return String(Pos(p), p[0][1:-1], VarTypeName(Pos(p), "str"))

    # other constants

    @_("TRUE")
    def expr(self, p):
        return Constant(Pos(p), 1, VarTypeName(Pos(p), "bool"))

    @_("FALSE")
    def expr(self, p):
        return Constant(Pos(p), 0, VarTypeName(Pos(p), "bool"))

    #################################################################
    # Argument list definition
    #################################################################

    # Used for function definition signatures
    # Arglists and exprlists are deliberately different entities

    @_("LPAREN empty RPAREN")
    def arglist(self, p):
        return []

    @_("LPAREN args RPAREN")
    def arglist(self, p):
        return p.args

    @_("args COMMA arg")
    def args(self, p):
        return p.args + [p.arg]

    @_("arg")
    def args(self, p):
        return [p.arg]

    @_("NAME varassign")
    def arg(self, p):
        return Argument(Pos(p), p.NAME, *p.varassign)

    @_("optvartype argassign")
    def varassign(self, p):
        return p.optvartype, p.argassign

    @_("ASSIGN expr")
    def argassign(self, p):
        return p.expr

    @_("empty")
    def argassign(self, p):
        return None

    #################################################################
    # Vartypes
    #################################################################

    @_("vartype")
    def optvartype(self, p):
        return p.vartype

    @_("empty")
    def optvartype(self, p):
        return VarTypeName(Pos(p), None)

    @_("COLON vartypedef")
    def vartype(self, p):
        return p.vartypedef

    @_("NAME")
    def vartypekind(self, p):
        return VarTypeName(Pos(p), p.NAME)

    @_("FUNC LPAREN vartypelist RPAREN vartype")
    def vartypekind(self, p):
        func = VarTypeFunc(Pos(p), p.vartypelist, p.vartype)
        return func

    @_("vartypelist COMMA vartype")
    def vartypelist(self, p):
        return p.vartypelist + [p.vartype]
        return

    @_("vartype")
    def vartypelist(self, p):
        return [p.vartype]

    @_("empty")
    def vartypelist(self, p):
        return []

    # pointer prefix

    @_("ptrlist vartypekind")
    def vartypedef(self, p):
        name = p.vartypekind
        for _ in p.ptrlist:
            name = VarTypePtr(Pos(p), name)
        return name

    @_("PTR ptrlist")
    def ptrlist(self, p):
        return [p.PTR] + p.ptrlist

    @_("PTR")
    def ptrlist(self, p):
        return [p.PTR]

    @_("empty")
    def ptrlist(self, p):
        return []

    #################################################################
    # `var` expressions
    #################################################################

    @_("varlist")
    def expr(self, p):
        return p.varlist

    @_("VAR varlistelements")
    def varlist(self, p):
        return VarList(Pos(p), p.varlistelements)

    @_("NAME optvartype")
    def varlistelement(self, p):
        return Name(Pos(p), p.NAME, None, p.optvartype)

    @_("NAME optvartype ASSIGN expr")
    def varlistelement(self, p):
        return Name(Pos(p), p.NAME, p.expr, p.optvartype)

    @_("varlistelements COMMA varlistelement")
    def varlistelements(self, p):
        return p.varlistelements + [p.varlistelement]

    @_("varlistelement")
    def varlistelements(self, p):
        return [p.varlistelement]

    #################################################################
    # Ops
    #################################################################

    # BinOp = expressions that evaluate to a numerical value

    @_(
        "expr PLUS expr",
        "expr MINUS expr",
        "expr TIMES expr",
        "expr DIV expr",
        "expr INT_DIV expr",
        "expr AND expr",
        "expr OR expr",
        "expr BIN_AND expr",
        "expr BIN_OR expr",
    )
    def expr(self, p):
        return BinOp(Pos(p), p[1], p.expr0, p.expr1)

    # binop math

    @_("MINUS expr %prec UMINUS")
    def expr(self, p):
        return UnOp(Pos(p), p[0], p.expr)

    @_("NOT expr %prec UMINUS")
    def expr(self, p):
        return UnOp(Pos(p), p[0], p.expr)

    # BinOpComparison = expressions that evaluate to true or false

    @_(
        "expr EQ expr",
        "expr NEQ expr",
        "expr GEQ expr",
        "expr LEQ expr",
        "expr GT expr",
        "expr LT expr",
    )
    def expr(self, p):
        return BinOpComparison(Pos(p), p[1], p.expr0, p.expr1)

    #################################################################
    # assignment
    #################################################################

    @_("NAME ASSIGN expr")
    def assignment_expr(self, p):
        return Assignment(Pos(p), p[1], Name(Pos(p), p[0]), p.expr)

    @_("assignment_expr")
    def expr(self, p):
        return p.assignment_expr

    @_("NAME INCR expr", "NAME DECR expr")
    def expr(self, p):
        # n+=expr / n-=expr are encoded as n=n+expr
        return Assignment(
            Pos(p),
            "=",
            Name(Pos(p), p[0]),
            BinOp(Pos(p), p[1][0], Name(Pos(p), p[0]), p.expr),
        )

    #################################################################
    # Function call
    #################################################################

    @_("NAME LPAREN exprlist RPAREN")
    def expr(self, p):
        return Call(Pos(p), p.NAME, p.exprlist, None)

    # Expression list

    @_("empty")
    def exprlist(self, p):
        return []

    @_("exprs")
    def exprlist(self, p):
        return p.exprs

    @_("exprs COMMA expr")
    def exprs(self, p):
        return p.exprs + [p.expr]

    @_("expr")
    def exprs(self, p):
        return [p.expr]

    #################################################################
    # Flow control
    #################################################################

    # "if/when" expressions

    @_("when_expr")
    def expr(self, p):
        return p.when_expr

    @_("if_expr")
    def expr(self, p):
        return p.if_expr

    @_("IF expr_block expr_block ELSE expr_block")
    def if_expr(self, p):
        return IfExpr(Pos(p), p.expr_block0, p.expr_block1, p.expr_block2)

    @_("IF expr_block expr_block empty")
    def when_expr(self, p):
        return WhenExpr(Pos(p), p.expr_block0, p.expr_block1, None)

    @_("WHEN expr_block expr_block ELSE expr_block")
    def when_expr(self, p):
        return WhenExpr(Pos(p), p.expr_block0, p.expr_block1, p.expr_block2)

    @_("WHEN expr_block expr_block empty")
    def when_expr(self, p):
        return WhenExpr(Pos(p), p.expr_block0, p.expr_block1, None)

    # "loop" expressions

    # TODO: replace with regular var list
    @_("VAR varlistelement", "assignment_expr")
    def loop_expr_var(self, p):
        if isinstance(p[0], Assignment):
            return p.assignment_expr
        return VarList(Pos(p), [p.varlistelement])

    @_("LOOP LPAREN loop_expr_var COMMA expr COMMA expr RPAREN expr_block")
    def loop_expr(self, p):
        return LoopExpr(Pos(p), [p.loop_expr_var, p.expr0, p.expr1], p.expr_block)

    @_("LOOP empty expr_block", "LOOP LPAREN RPAREN expr_block")
    def loop_expr(self, p):
        return LoopExpr(Pos(p), [], p.expr_block)

    @_("loop_expr")
    def expr(self, p):
        return p.loop_expr

    # "break" expressions

    @_("BREAK")
    def expr(self, p):
        return Break(Pos(p))

    # "with" expressions

    @_("WITH varlist expr_block")
    def with_expr(self, p):
        return WithExpr(Pos(p), p.varlist, p.expr_block)

    @_("with_expr")
    def expr(self, p):
        return p.with_expr

    #################################################################
    # Expression chain (to come)
    #################################################################

    @_("exprchain")
    def expr(self, p):
        return p.exprchain

    @_("expr DOT dotexprlist")
    def exprchain(self, p):
        return ChainExpr(Pos(p), [p.expr]+p.dotexprlist)
    
    @_("dotexprlist DOT expr")
    def dotexprlist(self, p):
        return p.dotexprlist + [p.expr]
    
    @_("expr")
    def dotexprlist(self, p):
        return [p.expr]    

    #################################################################
    # Slice
    #################################################################

    # @_("slice_expr")
    # def expr(self, p):
    #     return p.slice_expr

    # @_("expr LBRACKET slice_list RBRACKET")
    # def slice_expr(self, p):
    #     pass

    #################################################################
    # Accessor
    #################################################################

    # @_("accessor_expr")
    # def expr(self, p):
    #     return p.accessor_expr

    # @_("expr LBRACKET accessor_list RBRACKET")
    # def accessor_list(self, p):
    #     pass

    #################################################################
    # Empty
    #################################################################

    @_("")
    def empty(self, p):
        pass
