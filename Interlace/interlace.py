#!/usr/bin/python3
import typer

from typing import Optional, List
from typing_extensions import Annotated
from pathlib import Path

from Interlace.lib.core.input import InputHelper
from Interlace.lib.core.output import OutputHelper, Level
from Interlace.lib.threader import Pool


def task_queue_generator_func(arguments, output, repeat):
    tasks_data = InputHelper.process_data_for_tasks_iterator(arguments)
    tasks_count = tasks_data["tasks_count"]
    yield tasks_count
    tasks_generator_func = InputHelper.make_tasks_generator_func(tasks_data)
    for i in range(repeat):
        tasks_iterator = tasks_generator_func()
        for task in tasks_iterator:
            yield task


class ArgsNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


app = typer.Typer(add_completion=True)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    target: Annotated[Optional[str], typer.Option("--target", "-t", help="Specify a target or domain name either in comma format, CIDR notation, glob notation, or a single target.")] = None,
    target_list: Annotated[Optional[Path], typer.Option("--target-list", "-tL", help="Specify a list of targets or domain names.")] = None,
    exclusions: Annotated[Optional[str], typer.Option("--exclusions", "-e", help="Specify an exclusion either in comma format, CIDR notation, or a single target.")] = None,
    exclusions_list: Annotated[Optional[Path], typer.Option("--exclusions-list", "-eL", help="Specify a list of exclusions.")] = None,
    threads: Annotated[int, typer.Option("--threads", "-threads", help="Specify the maximum number of threads to run.")] = 5,
    timeout: Annotated[int, typer.Option("--timeout", "-timeout", help="Command timeout in seconds.")] = 600,
    command: Annotated[Optional[str], typer.Option("--command", "-c", help="Specify a single command to execute.")] = None,
    command_list: Annotated[Optional[Path], typer.Option("--command-list", "-cL", help="Specify a list of commands to execute")] = None,
    output_path: Annotated[Optional[str], typer.Option("--output", "-o", help="Specify an output folder variable that can be used in commands as _output_")] = None,
    port: Annotated[Optional[str], typer.Option("--port", "-p", help="Specify a port variable that can be used in commands as _port_")] = None,
    proxy_list: Annotated[Optional[Path], typer.Option("--proxy-list", "-pL", help="Specify a list of proxies.")] = None,
    proto: Annotated[Optional[str], typer.Option("--proto", help="Specify protocols that can be used in commands as _proto_")] = None,
    realport: Annotated[Optional[str], typer.Option("--realport", "-rp", help="Specify a real port variable that can be used in commands as _realport_")] = None,
    random: Annotated[Optional[Path], typer.Option("--random", "-random", help="Specify a directory of files that can be randomly used in commands as _random_")] = None,
    nocidr: Annotated[bool, typer.Option("--no-cidr", help="If set then CIDR notation in a target file will not be automatically be expanded into individual hosts.")] = False,
    nocolor: Annotated[bool, typer.Option("--no-color", help="If set then any foreground or background colours will be stripped out.")] = False,
    sober: Annotated[bool, typer.Option("--sober", "--no-bar", help="If set then progress bar will be stripped out")] = False,
    silent: Annotated[bool, typer.Option("--silent", help="If set only findings will be displayed and banners and other information will be redacted.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="If set then verbose output will be displayed in the terminal.")] = False,
    repeat: Annotated[int, typer.Option("--repeat", help="repeat the given command x number of times.")] = 1,
):
    """
    Easily turn single threaded command line applications into a fast, multi-threaded application with CIDR and glob support.
    """
    if ctx.invoked_subcommand is not None:
        return

    
    # Validate mutually exclusive groups
    if not target and not target_list:
        # Check if stdin has data? ArgumentParser logic had: if not sys.stdin.isatty(): requireTargetArg = False
        import sys
        if sys.stdin.isatty():
             typer.echo("Error: One of -t or -tL is required when not using stdin.", err=True)
             raise typer.Exit(code=1)

    if target and target_list:
        typer.echo("Error: -t and -tL are mutually exclusive.", err=True)
        raise typer.Exit(code=1)

    if exclusions and exclusions_list:
        typer.echo("Error: -e and -eL are mutually exclusive.", err=True)
        raise typer.Exit(code=1)

    if not command and not command_list:
        typer.echo("Error: One of -c or -cL is required.", err=True)
        raise typer.Exit(code=1)

    if command and command_list:
        typer.echo("Error: -c and -cL are mutually exclusive.", err=True)
        raise typer.Exit(code=1)

    if verbose and silent:
         typer.echo("Error: -v and --silent are mutually exclusive.", err=True)
         raise typer.Exit(code=1)
    
    # Convert Paths to file handles if necessary, or just strings?
    # InputHelper.readable_file opens the file. Typer Path won't open it.
    # Existing code expects open file handles for _list arguments?
    # Let's check InputHelper.readable_file again. It returns an open file handle.
    
    target_list_file = None
    if target_list:
        if not target_list.exists():
             typer.echo(f"The path {target_list} does not exist!", err=True)
             raise typer.Exit(code=1)
        target_list_file = open(target_list, "r")

    exclusions_list_file = None
    if exclusions_list:
         if not exclusions_list.exists():
             typer.echo(f"The path {exclusions_list} does not exist!", err=True)
             raise typer.Exit(code=1)
         exclusions_list_file = open(exclusions_list, "r")

    command_list_file = None
    if command_list:
         if not command_list.exists():
             typer.echo(f"The path {command_list} does not exist!", err=True)
             raise typer.Exit(code=1)
         command_list_file = open(command_list, "r")
         
    proxy_list_file = None # Wait, input helper reads it later using InputHelper._process_targets or similar?
    # InputHelper.process_data_for_tasks_iterator -> uses proxy_list...
    # Wait, InputHelper.make_tasks_generator_func iterates arguments.proxy_list
    # In InputParser, type=lambda x: InputHelper.readable_file(parser, x) -> returns file handle?
    # Let's check proxy_list usage again.
    # In make_tasks_generator_func: arguments.proxy_list is iterated. "proxy for proxy in (proxy.strip() for proxy in proxy_list) if proxy"
    # If it's a file handle, that works. If it's a list (from readlines), that works.
    
    # Actually, InputParser had: type=lambda x: InputHelper.readable_file(parser, x)
    # readable_file returns: open(arg, 'r')
    
    if proxy_list:
        if not proxy_list.exists():
             typer.echo(f"The path {proxy_list} does not exist!", err=True)
             raise typer.Exit(code=1)
        proxy_list_file = open(proxy_list, "r")


    # Construct arguments object mimicking argparse Namespace
    arguments = ArgsNamespace(
        target=target,
        target_list=target_list_file,
        exclusions=exclusions,
        exclusions_list=exclusions_list_file,
        threads=threads,
        timeout=timeout,
        command=command,
        command_list=command_list_file,
        output=output_path, # Note: argparse dest='output'
        port=port,
        proxy_list=proxy_list_file, # Wait, InputParser dest='proxy_list' (from pL)
        proto=proto,
        realport=realport,
        random=str(random) if random else None,
        nocidr=nocidr,
        nocolor=nocolor,
        sober=sober,
        silent=silent,
        verbose=verbose,
        repeat=repeat
    )

    output_helper = OutputHelper(arguments)
    output_helper.print_banner()

    pool = Pool(
        arguments.threads,
        task_queue_generator_func(arguments, output_helper, repeat),
        arguments.timeout,
        output_helper,
        arguments.sober,
        silent=arguments.silent,
        output_helper=output_helper
    )
    pool.run()


def run():
    app()

if __name__ == "__main__":
    run()
