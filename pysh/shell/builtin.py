import collections
import csv
import datetime
import grp
import os
import stat
import optparse
import pwd
import StringIO
import sys

from pysh.shell.pycmd import register_pycmd
from pysh.shell.pycmd import pycmd
from pysh.shell.pycmd import IOType
from pysh.shell.table import PyshTable, CreateTableFromIterableRows

# TODO(yunabe): Writes tests for all commands.

def file_to_array(f):
  return map(lambda line: line.rstrip('\r\n'), f.readlines())


class OptionParser(optparse.OptionParser):
  def exit(self, status=0, msg=None):
    if msg:
      sys.stderr.write(msg)
    raise Exception('OptionParser exit.')


class Permission(int):
  def __init__(self, val):
    int.__init__(self, val)

  def __str__(self):
    return ''.join((self.__to_rwx(self >> 6),
                    self.__to_rwx(self >> 3),
                    self.__to_rwx(self >> 0)))
                   
  def __to_rwx(self,  rwx):
    result = ['-'] * 3
    if rwx & (1 << 2):
      result[0] = 'r'
    if rwx & (1 << 1):
      result[1] = 'w'
    if rwx & (1 << 0):
      result[2] = 'x'
    return ''.join(result)


@pycmd(name='echo', inType=IOType.No)
def pycmd_echo(args, input, options):
  line = []
  for arg in args[1:]:
    if not isinstance(arg, basestring) and (
      isinstance(arg, collections.Iterable)):
      if line:
        yield ' '.join(line)
        line = []
      for e in arg:
        yield e
    else:
      line.append(str(arg))
  if line:
    yield ' '.join(line)


@pycmd(name='map')
def pycmd_map(args, input, options):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return (f(x) for x in input)


@pycmd(name='filter')
def pycmd_filter(args, input, options):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  cond = args[1]
  assert callable(cond)
  for x in input:
    if cond(x):
      yield x


@pycmd(name='reduce')
def pycmd_reduce(args, input, options):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return [reduce(f, input)]


def create_pyls_row(path, stats, fulltime):
  file_type = '?'
  if stat.S_ISDIR(stats.st_mode):
    file_type = 'd'
  elif stat.S_ISBLK(stats.st_mode):
    file_type = 'b'
  elif stat.S_ISLNK(stats.st_mode):
    file_type = 'l'
  elif stat.S_ISSOCK(stats.st_mode):
    file_type = 's'
  elif stat.S_ISFIFO(stats.st_mode):
    file_type = 'p'
  elif stat.S_ISCHR(stats.st_mode):
    file_type = 'c'
  elif stat.S_ISREG(stats.st_mode):
    file_type = '-'
  user = pwd.getpwuid(stats.st_uid).pw_name
  group = grp.getgrgid(stats.st_gid).gr_name
  permission = stats.st_mode & 0777
  st_mtime = stats.st_mtime
  if not fulltime:
    st_mtime = int(st_mtime)
  st_atime = stats.st_atime
  if not fulltime:
    st_atime = int(st_atime)
  mtime = datetime.datetime.fromtimestamp(st_mtime)
  atime = datetime.datetime.fromtimestamp(st_atime)
  return (file_type, Permission(permission),
          user, group, mtime, atime, path)


pyls_option_parser = OptionParser()
pyls_option_parser.add_option(
  '-d', '--directory', dest='dir', action='store_true',
  help=('list directory entries instead of contents, and do not '
        'dereference symbolic links'))
pyls_option_parser.add_option(
  '--fulltime', dest='fulltime', action='store_true',
  help=('like -l --time-style=full-iso'))


@pycmd(name='pyls')
def pycmd_pyls(args, input, options):
  opt, args = pyls_option_parser.parse_args(args)
  args = args[1:]
  if not args:
    args = [os.getcwd()]

  def generator():
    for arg in args:
      stats = os.lstat(arg)
      if stat.S_ISDIR(stats.st_mode) and not opt.dir:
        names = os.listdir(arg)
        names = filter(lambda name: not name.startswith('.'), names)
        for name in names:
          joined = os.path.join(arg, name)
          stats = os.lstat(joined)
          yield create_pyls_row(joined, stats, opt.fulltime)
        else:
          yield create_pyls_row(arg, stats, opt.fulltime)

  return PyshTable(('type', 'mode', 'user', 'group', 'mtime', 'atime', 'path'),
                   generator())


@pycmd(name='select')
def pycmd_where(args, input, options):
  assert len(args) == 2
  table = CreateTableFromIterableRows(input)
  return table.select(args[1], options.globals(), options.locals())


@pycmd(name='where')
def pycmd_where(args, input, options):
  assert len(args) == 2
  table = CreateTableFromIterableRows(input)
  return table.where(args[1], options.globals(), options.locals())


@pycmd(name='orderby')
def pycmd_orderby(args, input, options):
  assert len(args) == 2 or len(args) == 3
  table = CreateTableFromIterableRows(input)
  asc = True
  if len(args) == 3:
    args2 = args[2].lower()
    if args2 == 'desc':
      asc = False
    elif args2 != 'asc':
      raise Exception('args[2] must be desc or asc.')
  return table.orderby(args[1], asc, options.globals(), options.locals())


@pycmd(name='tocsv')
def pycmd_tocsv(args, input, options):
  table = CreateTableFromIterableRows(input)
  io = StringIO.StringIO()
  w = csv.writer(io)
  w.writerow(table.columns)
  for row in table:
    w.writerow(row.values())
  return io.getvalue().split('\r\n')[:-1]


@pycmd(name='fromcsv')
def pycmd_fromcsv(args, input, options):
  reader = csv.reader(input)
  table = None
  it = iter(reader)
  try:
    row0 = it.next()
  except StopIteration:
    return None

  return PyshTable(tuple(row0), it)


@pycmd(name='cd', inType=IOType.No, outType=IOType.No)
def pycmd_cd(args, input, options):
  assert len(args) == 2 or len(args) == 1
  if len(args) == 2:
    dir = args[1]
  else:
    dir = os.environ.get('HOME', '')
  if dir:
    os.chdir(dir)
  return ()
