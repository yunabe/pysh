import unittest

from pysh.shell.tokenizer import Tokenizer
from pysh.shell.parser import BinaryOp
from pysh.shell.parser import Parser
from pysh.shell.parser import Process
from pysh.shell.parser import DoubleQuotedStringExpander

from pysh.shell.tokenizer import (
  SPACE,
  SINGLE_QUOTED_STRING,
  DOUBLE_QUOTED_STRING,
  SUBSTITUTION,
  REDIRECT,
  PIPE,
  RIGHT_ARROW,
  BOLD_RIGHT_ARROW,
  LITERAL,
  AND_OP,
  OR_OP,
  PARENTHESIS_START,
  PARENTHESIS_END,
  SEMICOLON,
  BACKQUOTE,
  EOF,
)


class DoubleQuotedStringExpanderTest(unittest.TestCase):
  def test(self):
    expanded = DoubleQuotedStringExpander(
      'apple pie. a$bc e${fg}\t10 ${{1: "3}"}}')
    self.assertEquals([(SINGLE_QUOTED_STRING, "'apple pie. a'"),
                       (SUBSTITUTION, '$bc'),
                       (SINGLE_QUOTED_STRING, "' e'"),
                       (SUBSTITUTION, '${fg}'),
                       (SINGLE_QUOTED_STRING, "'\\t10 '"),
                       (SUBSTITUTION, '${{1: "3}"}}'),
                       ], list(expanded))


class ParserTest(unittest.TestCase):
  def test(self):
    input = 'echo hoge$foo || echo piyo && cat'
    parser = Parser(Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, BinaryOp))
    self.assertEquals('&&', ast.op)
    self.assertTrue(isinstance(ast.left, BinaryOp))
    self.assertEquals('||', ast.left.op)
    proc0 = ast.left.left
    self.assertTrue(isinstance(proc0, Process))
    self.assertEquals([[('literal', 'echo')],
                       [('literal', 'hoge'), ('substitution', '$foo')]],
                      proc0.args)
    self.assertFalse(proc0.redirects)
    proc1 = ast.left.right
    self.assertTrue(isinstance(proc1, Process))
    self.assertEquals([[('literal', 'echo')], [('literal', 'piyo')]],
                      proc1.args)
    self.assertFalse(proc1.redirects)
    proc2 = ast.right
    self.assertTrue(isinstance(proc2, Process))
    self.assertEquals([[('literal', 'cat')]], proc2.args)
    self.assertFalse(proc2.redirects)

  def testSemicolon(self):
    input = 'echo; cat;'
    parser = Parser(Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, BinaryOp))
    self.assertEquals(';', ast.op)
    self.assertTrue(isinstance(ast.left, Process))
    self.assertTrue(isinstance(ast.right, Process))

  def testBackquote(self):
    input = 'echo `echo foo`'
    parser = Parser(Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertTrue(isinstance(ast.args[1][0][1], Process))
    self.assertEquals([[(LITERAL, 'echo')], [(LITERAL, 'foo')]],
                      ast.args[1][0][1].args)


  def testBackquoteWithSpace(self):
    input = 'echo ` echo foo `'
    parser = Parser(Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertTrue(isinstance(ast.args[1][0][1], Process))
    self.assertEquals([[(LITERAL, 'echo')], [(LITERAL, 'foo')]],
                      ast.args[1][0][1].args)

  def testBackquoteWithSemicolon(self):
    input = 'echo `echo foo;`'
    parser = Parser(Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertTrue(isinstance(ast.args[1][0][1], Process))
    self.assertEquals([[(LITERAL, 'echo')], [(LITERAL, 'foo')]],
                      ast.args[1][0][1].args)

  def testBackquoteWithSemicolon(self):
    input = 'echo `echo foo | cat`'
    parser = Parser(Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertEquals('|', ast.args[1][0][1].op)


if __name__ == '__main__':
  unittest.main()
