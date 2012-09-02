import collections
import csv
import datetime
import os
import pwd
import StringIO

from pysh.shell.pycmd import register_pycmd
from pysh.shell.pycmd import pycmd
from pysh.shell.pycmd import IOType
from pysh.shell.table import Table

def file_to_array(f):
  return map(lambda line: line.rstrip('\r\n'), f.readlines())


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
def pycmd_echo(args, input):
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
def pycmd_map(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return (f(x) for x in input)


@pycmd(name='filter')
def pycmd_filter(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  cond = args[1]
  assert callable(cond)
  for x in input:
    if cond(x):
      yield x


@pycmd(name='reduce')
def pycmd_reduce(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return [reduce(f, input)]


@pycmd(name='readcsv')
def pycmd_readcsv(args, input):
  return csv.reader(input)

@pycmd(name='pyls')
def pycmd_pls(args, input):
  table = Table(['mode', 'user', 'group', 'mtime', 'atime', 'path'])
  for arg in args[1:]:
    stat = os.stat(arg)
    user = pwd.getpwuid(stat.st_uid).pw_name
    group = pwd.getpwuid(stat.st_gid).pw_name
    permission = stat.st_mode & 0777
    mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
    atime = datetime.datetime.fromtimestamp(stat.st_atime)
    table.add_row([Permission(permission), user, group, mtime, atime, arg])
  return table


@pycmd(name='where')
def pycmd_pls(args, input):
  assert len(args) == 2
  row = list(input)[0]
  table = row.table()
  return table.where(args[1])


@pycmd(name='orderby')
def pycmd_pls(args, input):
  assert len(args) == 2 or len(args) == 3
  row = list(input)[0]
  table = row.table()
  asc = True
  if len(args) == 3:
    args2 = args[2].lower()
    if args2 == 'desc':
      asc = False
    elif args2 != 'asc':
      raise Exception('args[2] must be desc or asc.')
  return table.orderby(args[1], asc)


@pycmd(name='cd', inType=IOType.No, outType=IOType.No)
def pycmd_cd(args, input):
  assert len(args) == 2 or len(args) == 1
  if len(args) == 2:
    dir = args[1]
  else:
    dir = os.environ.get('HOME', '')
  if dir:
    os.chdir(dir)
  return ()
