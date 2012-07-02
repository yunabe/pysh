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

# Features
## Variable
In pysh, you can use python variable from shell scripts.

    x = 3
    y = x * x
    > echo $i
    > echo $PATH

## Python expression
In pysh, you can use any python expression by ${…}.

    > echo ${3 + 4}
    def f(x):
        return x * x
    > echo ${f(10)}
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

    > echo "a\nb"
    > echo "$i"
    > echo '$i'

## Backquote
Not yet supported
