import unittest

from core.parsing import Parser
from core.ast_module import Function, Number, DEFAULT_PREC, Prototype


class TestParser(unittest.TestCase):

    parser = Parser()

    maxDiff = None

    def _assert_body(self, toplevel, expected):
        """Assert the flattened body of the given toplevel function"""
        self.assertIsInstance(toplevel, Function)
        self.assertEqual(toplevel.body.flatten(), expected)

    def test_basic(self):
        ast = self.parser.parse_toplevel('2')
        self.assertIsInstance(ast, Function)
        self.assertIsInstance(ast.body, Number)
        self.assertEqual(ast.body.val, 2)

    def test_basic_with_flattening(self):
        ast = self.parser.parse_toplevel('2')
        self._assert_body(ast, ['Number', 2, self.parser.vartypes._DEFAULT_TYPE])

        ast = self.parser.parse_toplevel('foobar')
        self._assert_body(ast, ['Variable', 'foobar', None, None])

    def test_expr_singleprec(self):
        ast = self.parser.parse_toplevel('2+3-4')
        self._assert_body(ast, [
            'Binary', '-', [
                'Binary', '+', ['Number', 2, self.parser.vartypes._DEFAULT_TYPE],
                ['Number', 3, self.parser.vartypes._DEFAULT_TYPE]
            ], ['Number', 4, self.parser.vartypes._DEFAULT_TYPE]
        ])

    def test_expr_multiprec(self):
        ast = self.parser.parse_toplevel('2+3*4-9')
        self._assert_body(ast, [
            'Binary', '-', [
                'Binary', '+', ['Number', 2, self.parser.vartypes._DEFAULT_TYPE], [
                    'Binary', '*', ['Number', 3, self.parser.vartypes._DEFAULT_TYPE],
                    ['Number', 4, self.parser.vartypes._DEFAULT_TYPE]
                ]
            ], ['Number', 9, self.parser.vartypes._DEFAULT_TYPE]
        ])

    def test_expr_parens(self):
        ast = self.parser.parse_toplevel('2.*(3.-4.)*7.')
        self._assert_body(ast, [
            'Binary', '*', [
                'Binary', '*', ['Number', 2.0, self.parser.vartypes.f64], [
                    'Binary', '-', ['Number', 3.0, self.parser.vartypes.f64],
                    ['Number', 4.0, self.parser.vartypes.f64]
                ]
            ], ['Number', 7.0, self.parser.vartypes.f64]
        ])

    def test_externals(self):
        ast = self.parser.parse_toplevel('extern sin(arg)')
        self.assertEqual(ast.flatten(), ['Prototype', 'sin', 'i32 arg'])

        ast = self.parser.parse_toplevel('extern Foobar(nom denom abom)')
        self.assertEqual(ast.flatten(), [
            'Prototype', 'Foobar', 'i32 nom, i32 denom, i32 abom'
        ])

    def test_funcdef(self):
        ast = self.parser.parse_toplevel('def foo(x) 1 + bar(x)')

        self.assertEqual(ast.flatten(), [
            'Function', ['Prototype', 'foo', 'i32 x'], [
                'Binary', '+', ['Number', 1, self.parser.vartypes._DEFAULT_TYPE],
                ['Variable', 'bar', None,
                 ['Call', 'bar', None,
                  [['Variable', 'x', None, None]]
                  ]
                 ]
            ]]
        )

    def test_unary(self):        
        ast = self.parser.parse_toplevel('def unary!(x) 0 - x')
        self.assertIsInstance(ast, Function)
        proto = ast.proto
        self.assertIsInstance(proto, Prototype)
        self.assertTrue(proto.isoperator)
        self.assertEqual(proto.name, 'unary.!')

        ast = self.parser.parse_toplevel('!a + !b - !!c')
        self._assert_body(ast, [
            'Binary', '-', [
                'Binary', '+', ['Unary', '!', ['Variable', 'a', None, None]],
                ['Unary', '!', ['Variable', 'b', None, None]]
            ], ['Unary', '!', ['Unary', '!', ['Variable', 'c', None, None]]]
        ])

    def test_binary_op_no_prec(self):
        ast = self.parser.parse_toplevel('def binary~ (a, b) a + b')
        self.assertIsInstance(ast, Function)
        proto = ast.proto
        self.assertIsInstance(proto, Prototype)
        self.assertTrue(proto.isoperator)
        self.assertEqual(proto.prec, DEFAULT_PREC)
        self.assertEqual(proto.name, 'binary.~')

    def test_binary_op_with_prec(self):
        ast = self.parser.parse_toplevel('def binary% 77(a, b) a + b')
        self.assertIsInstance(ast, Function)
        proto = ast.proto
        self.assertIsInstance(proto, Prototype)
        self.assertTrue(proto.isoperator)
        self.assertEqual(proto.prec, 77)
        self.assertEqual(proto.name, 'binary.%')

    def test_binop_relative_precedence(self):
        # with precedence 77, % binds stronger than all existing ops
        p = Parser()
        p.parse_toplevel('def binary% 77(a, b) a + b')
        ast = p.parse_toplevel('a * 10 % 5 * 10')
        self._assert_body(ast, [
            'Binary', '*', [
                'Binary', '*', ['Variable', 'a', None, None], [
                    'Binary', '%', ['Number', 10, self.parser.vartypes._DEFAULT_TYPE],
                    ['Number', 5, self.parser.vartypes._DEFAULT_TYPE]
                ]
            ], ['Number', 10, self.parser.vartypes._DEFAULT_TYPE]
        ])

        ast = p.parse_toplevel('a % 20 * 5')
        self._assert_body(ast, [
            'Binary', '*', [
                'Binary', '%', ['Variable', 'a', None, None],
                ['Number', 20, self.parser.vartypes._DEFAULT_TYPE]
            ], ['Number', 5, self.parser.vartypes._DEFAULT_TYPE]
        ])

    def test_binop_right_associativity(self):
        p = Parser()
        ast = p.parse_toplevel('x = y = 10 + 5')
        self._assert_body(ast, [
            'Binary', '=', ['Variable', 'x', None, None], [
                'Binary', '=', ['Variable', 'y', None, None], [
                    'Binary', '+', ['Number', 10, self.parser.vartypes._DEFAULT_TYPE],
                    ['Number', 5, self.parser.vartypes._DEFAULT_TYPE]
                ]
            ]
        ])
