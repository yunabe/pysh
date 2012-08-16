import os
import tempfile
import shutil
import unittest

from pysh.shell.builtin import register_builtin
from pysh.shell.evaluator import run

register_builtin()

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

  def testSendData(self):
    data = ['foo', 'bar', 'baz']
    run('send $data | sort > out.txt', globals(), locals())
    self.assertEquals('bar\nbaz\nfoo\n', file('out.txt').read())

  def testMapCmd(self):
    run('echo "1\\n2\\n3\\n4\\n5" | map ${lambda l: int(l)} |'
             'map ${lambda x: x * x} > out.txt', globals(), locals())
    self.assertEquals('1\n4\n9\n16\n25\n', file('out.txt').read())

  def testFilterCmd(self):
    run('echo "cupcake\\ndonut\\nfroyo\\nginger" |'
             'filter ${lambda l: "e" in l} > out.txt',
             globals(), locals())
    self.assertEquals('cupcake\nginger\n', file('out.txt').read())

  def testReduceCmd(self):
    run('echo "foo\\nbar" | reduce ${lambda x, y: x + y} |'
             'cat > out.txt', globals(), locals())
    self.assertEquals('foobar\n', file('out.txt').read())

  def testReadCvsCmd(self):
    run('echo \'a,b,"c,"\' > in.txt', globals(), locals())
    run('echo \'e,"f","""g"""\' >> in.txt', globals(), locals())
    run('cat in.txt | readcsv |'
             'map ${lambda row: row[2]} > out.txt',
             globals(), locals())
    self.assertEquals('c,\n"g"\n', file('out.txt').read())

  def testChangeDir(self):
    rc = run('cd /dev', globals(), locals())
    self.assertEquals('/dev', os.getcwd())

  def testChangeDirHome(self):
    rc = run('cd', globals(), locals())
    self.assertEquals(os.environ['HOME'], os.getcwd())

if __name__ == '__main__':
  unittest.main()
