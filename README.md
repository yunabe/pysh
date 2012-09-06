#pysh

Write shell scripts in Python

## Basic
In pysh, You can write shell scripts as normal Python script.

    if not name:
        name = 'world'
    print 'Hello %!' % name

When you want to use useful features in shell script like
command execution, pipe, redirection,

    if not name:
        name = 'world'
    > echo "Hello $name!"

## pysh command
### Run scripts from files

    pysh script.pysh

### Run scripts from stdin

    pysh - << 'EOF' arg0 arg1
    import sys
    > echo ${str(sys.argv[1:])}
    EOF

# Features
## Variable
In pysh, you can use python variable from shell scripts.

    x = 3
    y = x * x
    > echo $y     # 9
    > echo $PATH  # os.environment['PATH']

## Python expression
In pysh, you can use any python expression by ${…}.

    > echo ${3 + 4}  # 7
    def f(x):
        return x * x
    > echo ${f(10)}  # 100
    > echo ${lambda x: x}

## Pipe
Pipe is supported in pysh.

    > echo "foo\nbar" | tac

## Redirection
Redirection is also supported in pysh.

    > echo "Hello world" > /dev/null
    > echo "Hello world" >> /dev/null
    > echo "Hello world" 2>&1

## ; && ||

    > echo foo; echo bar
    > echo foo && echo bar
    > echo foo || echo bar

## String literal
The format of string literal in pysh is equivalent with
string literal in Python
(In other words, it's different from other shells.)
You can use escape characters like \n, \t.
If you are familiar with Python, you don't need to learn another
string literal format.

    > echo "a\nb"

In pysh, variables ($i) and python expression (${…}) in string literals
are evaluated if string literal is double-quoted.
If string literal is single-quoted, pysh does not evaluate $i, ${…} in literals.
    
    > echo "$i"
    > echo '$i'

## map, reduce, filter
map, reduce and filter builtin commands are available in pysh.
These commands read data from pipe and apply "python" function in arg.

### map

    > seq 10 | map ${lambda s: int(s) * int(s)}
    1
    4
    9
    ...

### filter

    > seq 10 | filter ${lambda s: int(s) % 3 == 0}
    3
    6
    9

### reduce

    > seq 10 | reduce ${lambda x, y: int(x) + int(y)}
    55

## Multiline
Like other shell script, you can continue lines
with backslash at the end of line.

    > echo foo\
        bar

## Store return code
You can store return code of programs with ->.

    > (python -c 'import sys;sys.exit(2)' -> rc0\
        || python -c 'import sys;sys;exit(0)' -> rc1)
    > print rc0, rc1  # 512 0

## Redirect to Python
You can redirect output to Python variable with =>.
The output is stored to Python variable as list
(each line is stored as each element of a list).

    > seq 5 | grep -v 3 => out
    print out  # ['1', '2', '4', '5']
    > send ${xrange(5)} | filter ${lambda i: i != 3} => out
    print out  # [0, 1, 2, 4]
    
## Backquote
You can use backquote to use results of commands as command arguments.

    > echo `expr 3 + 4`  # 7
