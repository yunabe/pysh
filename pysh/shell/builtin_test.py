import os
import tempfile
import shutil
import unittest

import pysh.shell.builtin
from pysh.shell.table import PyshTable
from pysh.shell.evaluator import run


class TempDir(object):
  def __init__(self):
    self.path = None

  def __enter__(self):
    self.path = tempfile.mkdtemp()
    return self

  def __exit__(self, type, value, traceback):
    if not self.path:
      return
    try:
      shutil.rmtree(self.path)
    except OSError, e:
      if e.errno != 2:
        raise
    self.path = None


class BuiltinTest(unittest.TestCase):
  def setUp(self):
    self.original_dir = os.getcwd()
    self.tmpdir = TempDir()
    self.tmpdir.__enter__()
    os.chdir(self.tmpdir.path)

  def tearDown(self):
    self.tmpdir.__exit__(None, None, None)
    os.chdir(self.original_dir)

  def testEchoString(self):
    run('echo foo bar "piyo" | sort > out.txt', globals(), locals())
    self.assertEquals('foo bar piyo\n', file('out.txt').read())

  def testEchoList(self):
    data = ['foo', 'bar', 'baz']
    run('echo $data > out.txt', globals(), locals())
    self.assertEquals('foo\nbar\nbaz\n', file('out.txt').read())

  def testEchoTuple(self):
    data = ('foo', 'bar', 'baz')
    run('echo $data > out.txt', globals(), locals())
    self.assertEquals('foo\nbar\nbaz\n', file('out.txt').read())

  def testEchoXrange(self):
    data = xrange(3)
    run('echo $data > out.txt', globals(), locals())
    self.assertEquals('0\n1\n2\n', file('out.txt').read())

  def testEchoMix(self):
    data = ['foo', 'bar']
    run('echo a $data b > out.txt', globals(), locals())
    self.assertEquals('a\nfoo\nbar\nb\n', file('out.txt').read())

  def testMapCmd(self):
    run('/bin/echo "1\\n2\\n3\\n4\\n5" | map ${lambda l: int(l)} |'
             'map ${lambda x: x * x} > out.txt', globals(), locals())
    self.assertEquals('1\n4\n9\n16\n25\n', file('out.txt').read())

  def testFilterCmd(self):
    run('/bin/echo "cupcake\\ndonut\\nfroyo\\nginger" |'
             'filter ${lambda l: "e" in l} > out.txt',
             globals(), locals())
    self.assertEquals('cupcake\nginger\n', file('out.txt').read())

  def testReduceCmd(self):
    run('/bin/echo "foo\\nbar" | reduce ${lambda x, y: x + y} |'
             'cat > out.txt', globals(), locals())
    self.assertEquals('foobar\n', file('out.txt').read())

  def testChangeDir(self):
    rc = run('cd /dev', globals(), locals())
    self.assertEquals('/dev', os.getcwd())

  def testChangeDirHome(self):
    rc = run('cd', globals(), locals())
    self.assertEquals(os.environ['HOME'], os.getcwd())

  def testWhere(self):
    table = PyshTable(('a', 'b'),
                      ((i, i * i % 10) for i in xrange(10)))
    rc = run('echo $table | where "a == 3" => out', globals(), locals())
    self.assertEquals(1, len(rc['out']))
    self.assertEquals((3, 9), (rc['out'][0].a, rc['out'][0].b))

  def testOrderby(self):
    table = PyshTable(('a', 'b'),
                      ((i, i * i % 10) for i in xrange(10)))
    rc = run('echo $table | orderby b desc => out', globals(), locals())
    self.assertEquals(10, len(rc['out']))
    self.assertEquals(9, rc['out'][0].b)


if __name__ == '__main__':
  unittest.main()
