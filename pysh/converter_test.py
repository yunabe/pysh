import StringIO
import unittest

from pysh.converter import RoughLexer
from pysh.converter import Converter

class RoughLexerTest(unittest.TestCase):
  def testSimplePython(self):
    reader = StringIO.StringIO('print 3 + 4')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print 3 + 4'), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testSimplePython(self):
    reader = StringIO.StringIO('print 3 + 4\\\n + 5')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print 3 + 4 + 5'), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testSimpleShell(self):
    reader = StringIO.StringIO('> echo foo\\\n bar')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'shell', 'echo foo bar'), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testString(self):
    reader = StringIO.StringIO('print "apple"\nprint \'banana\'')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print "apple"'), lexer.next())
    self.assertEquals(('', 'python', 'print \'banana\''), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testEscapeInString(self):
    content = '"apple\\"tbanana" \'cake\\\'donuts\''
    reader = StringIO.StringIO(content)
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', content), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testBackslashInString(self):
    content = '"apple\\\nbanana"'
    reader = StringIO.StringIO(content)
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', '"applebanana"'), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testHereDocument(self):
    reader = StringIO.StringIO('print """apple"""\nprint \'\'\'banana\'\'\'')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print """apple"""'), lexer.next())
    self.assertEquals(('', 'python', 'print \'\'\'banana\'\'\''), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testHereDocument(self):
    reader = StringIO.StringIO('print """apple"""\nprint \'\'\'banana\'\'\'')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print """apple"""'), lexer.next())
    self.assertEquals(('', 'python', 'print \'\'\'banana\'\'\''), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testEscapeHereDocument(self):
    reader = StringIO.StringIO('print """\\""""')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print """\\""""'), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testBackslashInHereDocument(self):
    content = '"""apple\\\nbanana"""'
    reader = StringIO.StringIO(content)
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', '"""applebanana"""'), lexer.next())
    self.assertEquals((None, None, None), lexer.next())

  def testComment(self):
    reader = StringIO.StringIO('print 10 # comment')
    lexer = RoughLexer(reader)
    self.assertEquals(('', 'python', 'print 10 '), lexer.next())
    self.assertEquals((None, None, None), lexer.next())


class ConverterTest(unittest.TestCase):
  def testExtractResponseNames(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames('echo foo -> bar')
    self.assertEquals(['bar'], names)

  def testExtractResponseNames_Redirection(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames('echo foo => bar')
    self.assertEquals(['bar'], names)

  def testExtractResponseNames_InBinaryOp(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames('echo foo -> bar && echo baz => qux')
    self.assertEquals(['bar', 'qux'], names)

  def testExtractResponseNames_InAssignCmd(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames(
      '(echo foo -> bar && echo baz => qux) -> piyo')
    self.assertEquals(['bar', 'qux', 'piyo'], names)



if __name__ == '__main__':
  unittest.main()
