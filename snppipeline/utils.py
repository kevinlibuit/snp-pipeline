from __future__ import print_function
from __future__ import absolute_import
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
import locale
import os
import platform
import pprint
import psutil
import re
import sys
import subprocess
import time
import traceback
import vcf

from snppipeline.__init__ import __version__
from snppipeline import command


#==============================================================================
#Prep work
#==============================================================================

log_verbosity = 0


#==============================================================================
#Define functions
#==============================================================================

def set_logging_verbosity(args):
    """Enable or disable logging.

    Args:
        verbose : Verbosity value, any value greater than 0 enables logging
    """
    global log_verbosity
    log_verbosity = args.verbose


def verbose_print(*args):
    """Print messages conditionally depending on the configured verbosity.
    """
    if log_verbosity > 0:
        print(*args)


def timestamp():
    """Return a timestamp string."""
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def program_name():
    """Return the basename of the python script being executed."""
    return os.path.basename(sys.argv[0])


def program_name_with_command():
    """Return the basename of the python script being executed with the
    subcommand if possible."""
    program = os.path.basename(sys.argv[0])
    if program == "cfsan_snp_pipeline":
        program += " " + sys.argv[1]
    return program


def command_line_short():
    """Return the command line string without the full path to the program."""
    return "%s %s" % (program_name(), " ".join(sys.argv[1:]))


def command_line_long():
    """Return the command line string with the full path to the program."""
    return " ".join(sys.argv)


def print_log_header():
    """Print a standardized header for the log with starting conditions."""
    verbose_print("# Command           : %s" % command_line_long())
    verbose_print("# Working Directory : %s" % os.getcwd())
    pbs_jobid = os.environ.get("PBS_JOBID")
    sge_jobid = os.environ.get("JOB_ID")
    sge_task_id = os.environ.get("SGE_TASK_ID")
    if sge_task_id == "undefined":
        sge_task_id = None
    if pbs_jobid:
        verbose_print("# Job ID            : %s" % pbs_jobid)
    elif sge_jobid and sge_task_id:
        verbose_print("# Job ID            : %s[%s]" % (sge_jobid, sge_task_id))
    elif sge_jobid:
        verbose_print("# Job ID            : %s" % sge_jobid)

    verbose_print("# Hostname          : %s" % platform.node())
    locale.setlocale(locale.LC_ALL, '')
    ram_mbytes = psutil.virtual_memory().total / 1024 / 1024
    ram_str = locale.format("%d", ram_mbytes, grouping=True)
    verbose_print("# RAM               : %s MB" % ram_str)
    verbose_print("# Python Version    : %s" % sys.version.replace("\n", " "))
    verbose_print("# Program Version   : %s %s" % (program_name_with_command(), __version__))
    verbose_print("")
    verbose_print("# %s %s" % (timestamp(), command_line_short()))


def print_arguments(args):
    """Print the program options.

    Parameters
    ----------
    args : argparse.Namespace
        Pre-parsed program arguments
    """
    verbose_print("Options:")
    options_dict = vars(args)
    for key in list(options_dict.keys()):
        if key in ["subparser_name", "func", "excepthook"]:
            continue
        verbose_print("    %s=%s" % (key, options_dict[key]))


def detect_numeric_option_in_parameters_str(parameters, option):
    """
    Parses a string of options to find a particular option followed by its
    value.

    This function is used to determine whether a user is overriding a default
    parameter.

    Parameters
    ----------
    parameters : str
        String of multiple user-specified options with values
    option : str
        The particular option to look for.  Should have a leading '-' if expected.

    Returns
    -------
    found : bool
        True if the option is detected, false otherwise

    Examples
    --------
    >>> detect_numeric_option_in_parameters_str("-p1", "-p")
    True
    >>> detect_numeric_option_in_parameters_str("-p 1", "-p")
    True
    >>> detect_numeric_option_in_parameters_str("-p 22", "-p")
    True
    >>> detect_numeric_option_in_parameters_str("-a x -p 22 -z 44", "-p")
    True
    >>> detect_numeric_option_in_parameters_str("-p 22", "-n")
    False
    >>> detect_numeric_option_in_parameters_str("-p", "-p")
    False
    >>> detect_numeric_option_in_parameters_str("", "-p")
    False
    """
    regex_str = option + "[ ]*([0-9])+"
    regex = re.compile(regex_str)
    return regex.search(parameters) is not None


def extract_version_str(program_name, command_line):
    """Run a program with options to emit the version and construct
    a string with the program name a version.

    Parameters
    ----------
    program_name : str
        Friendly program name -- this will be returned in the version string
    command_line : str
        Command to be executed to get the version somewhere in the output

    Returns
    -------
    version_str : str
        A version string of the form "program_name version 2.3.0" or
        "Unrecognized program_name version".
    """
    # Run the command to get the version, split and clean the output
    text = command.run(command_line)
    lines = text.split('\n')
    lines = [line.strip() for line in lines]
    lines = [line for line in lines if line]

    # Look for an output line with the word "version"
    for line in lines:
        lowerline = line.lower()
        if "version" in lowerline:
            lowerline = lowerline.replace(':', ' ')
            tokens = lowerline.split()
            for index, token in enumerate(tokens):
                if token == "version" and len(tokens) > index+1:
                    return program_name + " version " + tokens[index+1]

    # if only one line and only one token, assume it is the version identifier
    if len(lines) == 1:
        tokens = lines[0].split()
        if len(tokens) == 1:
            return program_name + " version " + tokens[0]

    return "Unrecognized " + program_name + " version"


def global_error(message):
    """
    Log a fatal error to the error summary file and exit with error code 100
    to cause Sun Grid Engine to also detect the error.

    This method always stops pipeline execution, it does not care about the
    SnpPipeline_StopOnSampleError flag.

    Args:
        message : str
            Error message
    """
    # Log the event to the error log
    error_output_file = os.environ.get("errorOutputFile")
    if error_output_file:
        with open(error_output_file, "a") as err_log:
            print("%s failed." % program_name_with_command(), file=err_log)
            if message:
                print(message, file=err_log)
            print("=" * 80, file=err_log)

    # send the detail error message to stderr -- this will put the error
    # message in the process-specific log file.
    sys.stdout.flush() # make sure stdout is flushed before printing the error
    if message:
        print(message, file=sys.stderr)

    # Exit 100 does two things:
    # 1. Sun Grid Engine will stop execution of dependent jobs
    # 2. run_snp_pipeline.sh will know this error has already been reported
    sys.exit(100)


def sample_error(message, continue_possible=False):
    """
    Log an error to the error summary file and conditionally exit with error
    code 100 to cause Sun Grid Engine to also detect the error.

    The SnpPipeline_StopOnSampleError and continue_possible flags control the
    pipeline exit / continuation behavior.  Possible behaviors are:
    - Stop this step and all subsequent steps of the pipeline if
      SnpPipeline_StopOnSampleError is true or unset
    - Stop execution of this step, but continue subsequent steps if
      SnpPipeline_StopOnSampleError is false and continue_possible is false
    - Allow this step to continue if
      SnpPipeline_StopOnSampleError is false and continue_possible is true

    Args:
        message : str
            Error message
        continue_possible : boolean
            Indicates if it is possible to continue execution.  Setting this
            flag true may allow the code to continue without exiting if
            configured to do so.
    """
    stop_on_error_env = os.environ.get("SnpPipeline_StopOnSampleError")
    stop_on_error = stop_on_error_env is None or stop_on_error_env == "true"

    # Log the event to the error log
    error_output_file = os.environ.get("errorOutputFile")
    if error_output_file:
        with open(error_output_file, "a") as err_log:
            if stop_on_error or not continue_possible:
                print("%s failed." % program_name_with_command(), file=err_log)
            else:
                print("%s" % program_name_with_command(), file=err_log)
            print(message, file=err_log)
            print("=" * 80, file=err_log)

    # send the detail error message to stderr -- this will put the error
    # message in the process-specific log file.
    sys.stdout.flush() # make sure stdout is flushed before printing the error
    print(message, file=sys.stderr)

    # Exit 100 does two things:
    # 1. Sun Grid Engine will stop execution of dependent jobs
    # 2. run_snp_pipeline.sh will know this error has already been reported
    if stop_on_error:
        # run_snp_pipeline.sh will know this error has already been reported
        sys.exit(100)
    else:
        # run_snp_pipeline.sh will know this error has already been reported,
        # but it should not stop execution
        if not continue_possible:
            sys.exit(98)


def handle_global_exception(exc_type, exc_value, exc_traceback):
    """
    This function replaces the default python unhandled exception handler.
    It Logs the error and returns error code 100 to cause Sun Grid Engine to
    also detect the error.
    """

    # TODO: add the subprocess.CalledProcessError logic here.  See handle_sample_exception() below.

    # Report the exception in the error log if configuired
    error_output_file = os.environ.get("errorOutputFile")
    if error_output_file:
        with open(error_output_file, "a") as err_log:
            trace_entries = traceback.extract_tb(exc_traceback)
            file_name, line_number, function_name, code_text = trace_entries[-1]
            exc_type_name = exc_type.__name__

            print("Error detected while running %s." % program_name_with_command(), file=err_log)
            print("", file=err_log)
            print("The command line was:", file=err_log)
            print("    %s" % command_line_short(), file=err_log)
            print("", file=err_log)
            print("%s exception in function %s at line %d in file %s" % (exc_type_name, function_name, line_number, file_name), file=err_log)
            print("    %s" % code_text, file=err_log)
            print("=" * 80, file=err_log)

    # Report the exception in the usual way to stderr
    sys.stdout.flush() # make sure stdout is flushed before printing the trace
    traceback.print_exception(exc_type, exc_value, exc_traceback)

    # Exit 100 does two things:
    # 1. Sun Grid Engine will stop execution of dependent jobs
    # 2. run_snp_pipeline.sh will know this error has already been reported
    sys.exit(100)


def handle_sample_exception(exc_type, exc_value, exc_traceback):
    """
    This function replaces the default python unhandled exception handler.
    It Logs the error and returns error code 100 to cause Sun Grid Engine to
    also detect the error.
    """
    external_program_command = None
    if exc_type == subprocess.CalledProcessError:
        external_program_command = exc_value.cmd

    # Report the exception in the error log if configuired
    error_output_file = os.environ.get("errorOutputFile")
    if error_output_file:
        with open(error_output_file, "a") as err_log:
            trace_entries = traceback.extract_tb(exc_traceback)
            file_name, line_number, function_name, code_text = trace_entries[-1]
            exc_type_name = exc_type.__name__

            print("Error detected while running %s." % program_name_with_command(), file=err_log)
            print("", file=err_log)
            print("The command line was:", file=err_log)
            print("    %s" % command_line_short(), file=err_log)
            print("", file=err_log)
            if external_program_command:
                print("The error occured while running:", file=err_log)
                print("    %s" % external_program_command, file=err_log)
            else:
                print("%s exception in function %s at line %d in file %s" % (exc_type_name, function_name, line_number, file_name), file=err_log)
                print("    %s" % code_text, file=err_log)
            print("=" * 80, file=err_log)

    # Report the exception in the usual way to stderr
    sys.stdout.flush() # make sure stdout is flushed before printing the trace
    if external_program_command:
        print("Error occured while running:", file=sys.stderr)
        print("    %s" % external_program_command, file=sys.stderr)
    else:
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    # Exit 100 does two things:
    # 1. Sun Grid Engine will stop execution of dependent jobs
    # 2. run_snp_pipeline.sh will know this error has already been reported
    stop_on_error_env = os.environ.get("SnpPipeline_StopOnSampleError")
    stop_on_error = stop_on_error_env is None or stop_on_error_env == "true"
    if stop_on_error:
        # run_snp_pipeline.sh will know this error has already been reported
        sys.exit(100)
    else:
        # run_snp_pipeline.sh will know this error has already been reported,
        # but it should not stop execution
        sys.exit(98)


def report_error(message):
    """Send an error message to the error log and to stderr.
    """
    error_output_file = os.environ.get("errorOutputFile")
    if error_output_file:
        with open(error_output_file, "a") as err_log:
            print(message, file=err_log)

    # send the detail error message to stderr -- this will put the error
    # message in the process-specific log file.
    sys.stdout.flush() # make sure stdout is flushed before printing the error
    if message:
        print(message, file=sys.stderr)


def verify_existing_input_files(error_prefix, file_list):
    """Verify each file in a list of files exists.  It does
    not matter whether the file is empty.
    Missing files are reported in the verbose log.

    Args:
        error_prefix : first part of error message to be logged
        file_list : list of relative or absolute paths to files

    Returns:
        int number of missing files
    """
    bad_count = 0
    for file_path in file_list:

        if not os.path.isfile(file_path):
            bad_count += 1
            err_message = "%s %s does not exist." % (error_prefix, file_path)
            report_error(err_message)
            continue

    return bad_count


def verify_non_empty_input_files(error_prefix, file_list):
    """Verify each file in a list of files exists and is non-empty.
    Missing or empty files are reported in the verbose log.

    Args:
        error_prefix : first part of error message to be logged
        file_list : list of relative or absolute paths to files

    Returns:
        int number of missing or empty files
    """
    bad_count = 0
    for file_path in file_list:

        if not os.path.isfile(file_path):
            bad_count += 1
            err_message = "%s %s does not exist." % (error_prefix, file_path)
            report_error(err_message)
            continue
        if os.path.getsize(file_path) == 0:
            bad_count += 1
            err_message = "%s %s is empty." % (error_prefix, file_path)
            report_error(err_message)
            continue

    return bad_count


def target_needs_rebuild(source_files, target_file):
    """Determine if a target file needs a fresh rebuild, i.e. the target does
    not exist or its modification time is older than any of its source files.

    Args:
        source_files : relative or absolute path to a list of files
        target_file : relative or absolute path to target file
    """
    if not os.path.isfile(target_file):
        return True

    if os.path.getsize(target_file) == 0:
        return True

    target_timestamp = os.stat(target_file).st_mtime

    for source_file in source_files:
        # A non-existing source file should neither force a rebuild, nor prevent a rebuild.
        # You should error-check the existence of the source files before calling this function.
        #
        # An empty source file should force a rebuild if it is newer than the target, just like
        # a regular non-empty source file.
        if not os.path.isfile(source_file):
            continue

        source_timestamp = os.stat(source_file).st_mtime
        if source_timestamp > target_timestamp:
            return True

    return False


def targets_needs_rebuild(source_files, target_files):
    """Determine if target files need a fresh rebuild, i.e. any one of target files does
    not exist or its modification time is older than any of its source files.

    Args:
        source_files : relative or absolute path to a list of files
        target_files : relative or absolute path to a list of file
    """

    if len(target_files) == 0:
        return True
    else:
        if not os.path.isfile(target_files[0]):
            return True

        oldest_timestamp = os.stat(target_files[0]).st_mtime

        if os.path.getsize(target_files) == 0:
            return True

        for target_file in target_files:
            if (not os.path.isfile(target_file)) or (os.path.getsize(target_file) == 0):
                return True

            target_timestamp = os.stat(target_file).st_mtime
            if oldest_timestamp > target_timestamp:
                oldest_timestamp = target_timestamp

        for source_file in source_files:
            # A non-existing source file should neither force a rebuild, nor prevent a rebuild.
            # You should error-check the existence of the source files before calling this function.
            #
            # An empty source file should force a rebuild if it is newer than the target, just like
            # a regular non-empty source file.
            if not os.path.isfile(source_file):
                continue

            source_timestamp = os.stat(source_file).st_mtime
            if source_timestamp > oldest_timestamp:
                return True

    return False


def write_list_of_snps(file_path, snp_dict):
    """Write out list of snps for all samples to a single file.

    Args:
        file_path : path to snplist file to be written
        snp_dict  : dictionary with key = tuple(CHROM, POS) -> value = list[sampleName1, sampleName2, ..., sampleNameN]

    Returns:
        Nothing
    """

    with open(file_path, "w") as snp_list_file_object:
        for key in sorted(snp_dict.keys()):
            sample_list = snp_dict[key]
            snp_list_file_object.write("%s\t%d\t%d\t%s\n" % (key[0], key[1], len(sample_list), "\t".join(sample_list)))


def read_snp_position_list(snp_list_file_path):
    """Read list of snp positions across all samples from the snplist.txt.

    Args:
        snp_list_file_path : path to snplist file to be written

    Returns:
        snp_list  : sorted list of tuple(str(CHROM), int(POS))
    """

    snp_list = list()
    with open(snp_list_file_path, "r") as snp_list_file_object:
        for line in snp_list_file_object:
            chrom, pos = line.split()[0:2]
            snp_list.append((chrom, int(pos)))
    return snp_list


def write_reference_snp_file(reference_file_path, snp_list_file_path,
                             snp_reference_file_path):
    """Write out the snp fasta file for the reference.fasta using the snp
    position file ( snplist.txt).
    """
    #TODO finish documentation
    #TODO actual code is more general than stated. Fix this.

    with open(snp_list_file_path, "r") as snp_list_file:
        position_list = [line.split()[0:2] for line in snp_list_file]
    match_dict = SeqIO.to_dict(SeqIO.parse(reference_file_path, "fasta"))

    with open(snp_reference_file_path, "w") as snp_reference_file_object:
        for ordered_id in sorted(match_dict.keys()):
            ref_str = ""
            for chrom_id, pos in position_list:
                if chrom_id == ordered_id:
                    ref_str += match_dict[ordered_id][int(pos) - 1].upper()
            record = SeqRecord(Seq(ref_str), id=ordered_id, description="")
            SeqIO.write([record], snp_reference_file_object, "fasta")


def convert_vcf_file_to_snp_set(vcf_file_path):
    """convert vcf files to a set of SNPs.

    Args:
        vcf_file_path : relative or absolute path to the sample VCF file

    Returns:
        snp_set  : set of (CHROM, POS) tuples

    """

    snp_set = set()

    with open(vcf_file_path, 'r') as vcf_file_object:
        vcf_reader = vcf.Reader(vcf_file_object)
        for vcf_data_line in vcf_reader:
            key = (vcf_data_line.CHROM, vcf_data_line.POS)
            snp_set.add(key)

    return snp_set


def calculate_sequence_distance(seq1, seq2, case_insensitive=True):
    """Calulate the number of nucleotide differences between two sequences.

    The sequences must be the same length.

    Args:
        seq1 : DNA string 1
        seq2 : DNA string 2
        case_insensitive : optional flag for case insensitive compare, defaults to True

    Returns:
        int number of differences
    """
    if case_insensitive:
        allowed_bases = frozenset(['A', 'C', 'G', 'T'])
        seq1 = seq1.upper()
        seq2 = seq2.upper()
    else:
        allowed_bases = frozenset(['A', 'C', 'G', 'T', 'a', 'c', 'g', 't'])

    mismatches = 0
    for pos in range(len(seq1)):
        base1 = seq1[pos]
        base2 = seq2[pos]
        if base1 not in allowed_bases:
            continue
        if base2 not in allowed_bases:
            continue
        if base1 != base2:
            mismatches += 1
    return mismatches


#Both sort_coord and concensus are to combine bad regions
#as a lexical parsing problem.
def sort_coord(regions):
    """Given a list of regions, return a sorted list of starting and ending
    positions where each position is tagged with 's' or 'e' to indicate
    start or end.

    Parameters
    ----------
    regions : list of tuples
        List of (start, end) position integers.

    Returns
    -------
    coords : list of tuples
        List of (tag, position) where tag is 's' or 'e' sorted by position, then tag.
    """
    coords = []
    #add each start/end position into a new array as a tuple where the
    #first element represents whether it is a start or end
    for coord in regions:
        coords.append(('s', coord[0]))
        coords.append(('e', coord[1]))

    #sort by start and end first. In case of event where
    #a start and end coordinate are the same, we want the start
    #coordinate to come first.
    coords.sort(key=lambda x: x[0], reverse=True)

    #sort by coordinate
    coords.sort(key=lambda x: x[1])

    return coords


def consensus(coords):
    """Coalesce regions.

    Scans a sorted list of region starting and ending positions looking
    for the outer-most start and end positions to coalesce overlapping
    and contained regions into a smaller list of larger regions.

    Parameters
    ----------
    coords : list of tuples
        List of (tag, position) where tag is 's' or 'e' sorted by position, then tag.

    Returns
    -------
    regions : list of tuples
        List of (start, end) position integers.
    """
    count = 0
    posA = 0
    out = []
    for pos in coords:
        if count == 0:
            posA = pos[1]
        if pos[0] == 's':
            count += 1
        if pos[0] == 'e':
            count -= 1

        if count == 0:
            out.append((posA, pos[1]))

    return out


def overlap(coords):
    """A simple lexical tokenizer to find overlap.
    """
    count = 0
    posA = 0

    #this will tell you how many 'levels' there are
    #to the current overlap. Essentially how many
    #features makes up the overlap.
    level = 1
    out = []
    for pos in coords:
        if pos[0] == 's':
            count = 1
            level += 1
            posA = pos[1]
        if pos[0] == 'e':
            level -= 1
            count -= 1

        if count == 0:
            # Only output overlap if there are more than 1 feature making up the overlap
            if level > 1:
                out.append((posA, pos[1], level))

    return out


def in_region(pos, regions):
    """Find whether a position is included in a bad region.

    Parameters
    ----------
    pos : int
        DNA base position.
    regions : list of tuples
        List of (start, end) position integers.

    Returns
    -------
    bool
        True if the position is within an of the regions, False otherwise.
    """
    for region in regions:
        if (pos >= region[0]) and (pos <= region[1]):
            return True

    return False
