"""
VCF file writer.  Typical workflow would follow a pattern like this:

import vcf_writer
import pileup

caller = pileup.ConsensusCaller(min_freq, min_depth, min_strand_depth, min_strand_bias)
pileup_reader = pileup.Reader(file, min_base_quality, chrom_position_set=None)
writer = vcf_writer.SingleSampleWriter(out_file)
filters = caller.get_filter_descriptions()
writer.write_header(sample_id, filters, reference)
for pileup_record in pileup_reader:
    alt, fail_reasons = caller.call_consensus(record)
    writer.write_from_pileup(pileup_record, fail_reasons)
writer.close()
"""

from __future__ import print_function
from __future__ import absolute_import
import collections
import datetime
import sys
if sys.version_info < (3,):
    from StringIO import StringIO
else:
    from io import StringIO
import vcf
from snppipeline.__init__ import __version__
from snppipeline import pileup

VCF_VERSION = '##fileformat=VCFv4.2\n'
VCF_DATE    = '##fileDate=%Y%m%d\n'
VCF_SOURCE  = '##source=CFSAN SNP-Pipeline %s\n' % __version__
VCF_INFO    = '##INFO=<ID=NS,Number=1,Type=Integer,Description="Number of samples with data">\n'
VCF_FILTER  = '##FILTER=<ID=%s,Description="%s">\n'
VCF_FORMAT  = '''
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=SDP,Number=1,Type=Integer,Description="Raw read depth">
##FORMAT=<ID=RD,Number=1,Type=Integer,Description="Depth of reference-supporting bases">
##FORMAT=<ID=AD,Number=A,Type=Integer,Description="Depth of variant-supporting bases (comma-separated depth per alt allele)">
##FORMAT=<ID=RDF,Number=1,Type=Integer,Description="Depth of reference-supporting bases on forward strand">
##FORMAT=<ID=RDR,Number=1,Type=Integer,Description="Depth of reference-supporting bases on reverse strand">
##FORMAT=<ID=ADF,Number=A,Type=Integer,Description="Depth of variant-supporting bases on forward strand (comma-separated depth per alt allele)">
##FORMAT=<ID=ADR,Number=A,Type=Integer,Description="Depth of variant-supporting bases on reverse strand (comma-separated depth per alt allele)">
##FORMAT=<ID=FT,Number=1,Type=String,Description="Genotype filters using the same codes as the FILTER data element">
'''
VCF_REFERENCE = '##reference=%s\n'
VCF_HDR_LINE  = '#CHROM  POS     ID      REF     ALT     QUAL    FILTER  INFO    FORMAT  %s\n'


#==============================================================================
#Define classes and functions
#==============================================================================

class SingleSampleWriter(object):
    """
    Class to write VCF files for a single sample given records
    parsed by the pileup module.
    """

    def __init__(self, file, preserve_ref_case=False):
        """
        Initialize the VCF writer.

        Parameters
        ----------
        file : str or file stream
            Path to output vcf file or previously opened file stream.
        preserve_ref_case : boolean, optional
            If true, emit the reference base in the same uppercase/lowercase as
            the original reference fasta sequence.  If not specified, the
            reference base is emitted in uppercase.
        """
        if isinstance(file, str):
            self.file_path = file
            self.file_handle = open(file, "w")
        else:
            self.file_path = file.name
            self.file_handle = file

        self.preserve_ref_case = preserve_ref_case

    def close(self):
        """
        Close the VCF writer.
        This method should be called after iterating through all the records.
        """
        if self.pyvcf_writer:
            self.pyvcf_writer.close()
        self.file_handle.close()

    def write_header(self, sample_id, filters, reference):
        """
        Write the VCF file header with the standard SNP Pipeline data elements.

        Parameters
        ----------
        sample_id : str
            Sample ID which will be written to the header line.
        filters : list of tuple(str, str)
            List of names and descriptions of filters which will be combined
            and written to the header filter lines.
        reference : str
            Reference name which will be written to the header reference line.
        """
        # Write the template header to an in-memory buffer
        in_memory_file = StringIO()
        in_memory_file.name = "header.vcf"
        in_memory_file.write(VCF_VERSION)
        in_memory_file.write(datetime.datetime.strftime(datetime.datetime.now(), VCF_DATE))
        in_memory_file.write(VCF_SOURCE)
        in_memory_file.write(VCF_INFO)
        in_memory_file.write(VCF_FILTER % ("PASS", "All filters passed"))
        for name, description in filters:
            in_memory_file.write(VCF_FILTER % (name, description))
        in_memory_file.write(VCF_FORMAT)
        in_memory_file.write(VCF_REFERENCE % reference)
        in_memory_file.write(VCF_HDR_LINE % sample_id)

        # Rewind to the beginning of the file buffer to prepare for reading
        in_memory_file.seek(0)

        # Feed the template to pyVcf and write the header to our vcf file
        vcf_template = vcf.Reader(in_memory_file)
        self.pyvcf_writer = vcf.Writer(self.file_handle, template=vcf_template)

        # Extract the format string from the header.  It will be the same for
        # all positions, so only do this once.
        format_lines = VCF_FORMAT.split('\n')
        format_lines = [line for line in format_lines if len(line) > 0]
        format_lines = [line.replace("##FORMAT=<ID=", "") for line in format_lines]
        tokens = [line.split(',')[0] for line in format_lines]
        self.format_str = ':'.join(tokens)
        self.VcfCallData = collections.namedtuple('VcfCallData', tokens)  # this creates a new class called VcfCallData

    def _make_vcf_record_from_pileup(self, pileup_record, failed_filters, failed_snp_gt):
        """
        Create a PyVCF model record for a single sample from a single pileup
        record.

        Parameters
        ----------
        pileup_record : pileup.Record
            Previously parsed pileup record.
        failed_filters : list of str or None
            List of failed snp filters or None if all filters passed
        failed_snp_gt : str
            Controls the VCF file GT data element when a snp fails filters.  Possible values:
            "." : The GT element will be a dot, indicating unable to make a call (default)
            "0" : The GT element will be 0, indicating the reference base
            "1" : The GT element will be the ALT index of the most commonly occuring base, usually 1

        Returns
        -------
        record : vcf.model._Record
            PyVCF record with attributes describing chrom, pos, ref, alt, depth, etc.

        Examples
        --------
        >>> writer = SingleSampleWriter("/dev/null")
        >>> caller = pileup.ConsensusCaller(0.5, 1, 0, 0.0) # freq, depth, strand_depth, strand_bias
        >>> filters = caller.get_filter_descriptions()
        >>> writer.write_header("dummy-sample-name", filters, "dummy_reference-name")
        >>>
        >>> # Verify alternate allele is identified and called when it is the most common base
        >>> r = pileup.Record(['ID', 42, 'G', 14, 'aaaaAAAA...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, None, '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, [], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='1', SDP=14, RD=6, AD=[8], RDF=3, RDR=3, ADF=[4], ADR=[4], FT='PASS'))
        >>>
        >>> # Verify lowercase reference converted to uppercase when preserve_ref_case is False by default
        >>> r = pileup.Record(['ID', 42, 'g', 14, 'aaaaAAAA...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, None, '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, [], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='1', SDP=14, RD=6, AD=[8], RDF=3, RDR=3, ADF=[4], ADR=[4], FT='PASS'))
        >>>
        >>> # Failed snp, GT=.
        >>> r = pileup.Record(['ID', 42, 'g', 14, 'aaaaAAAA...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='.', SDP=14, RD=6, AD=[8], RDF=3, RDR=3, ADF=[4], ADR=[4], FT='Fail'))
        >>>
        >>> # Failed snp, GT=0
        >>> r = pileup.Record(['ID', 42, 'g', 14, 'aaaaAAAA...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '0')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='0', SDP=14, RD=6, AD=[8], RDF=3, RDR=3, ADF=[4], ADR=[4], FT='Fail'))
        >>>
        >>> # Failed snp, GT=1
        >>> r = pileup.Record(['ID', 42, 'g', 14, 'aaaaAAAA...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '1')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='1', SDP=14, RD=6, AD=[8], RDF=3, RDR=3, ADF=[4], ADR=[4], FT='Fail'))
        >>>
        >>> # Failed ref, GT=.
        >>> r = pileup.Record(['ID', 42, 'g', 14, '....,,,,aaaAAA', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='.', SDP=14, RD=8, AD=[6], RDF=4, RDR=4, ADF=[3], ADR=[3], FT='Fail'))
        >>>
        >>> # Failed ref, GT=0
        >>> r = pileup.Record(['ID', 42, 'g', 14, '....,,,,aaaAAA', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '0')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='0', SDP=14, RD=8, AD=[6], RDF=4, RDR=4, ADF=[3], ADR=[3], FT='Fail'))
        >>>
        >>> # Failed ref, GT=1
        >>> r = pileup.Record(['ID', 42, 'g', 14, '....,,,,aaaAAA', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '1')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='1', SDP=14, RD=8, AD=[6], RDF=4, RDR=4, ADF=[3], ADR=[3], FT='Fail'))
        >>>
        >>> # Verify the ref is called and the alternate allele is identified
        >>> r = pileup.Record(['ID', 42, 'G', 14, 'gaaaGGGG...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, None, '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, [], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='0', SDP=14, RD=11, AD=[3], RDF=7, RDR=4, ADF=[0], ADR=[3], FT='PASS'))
        >>>
        >>> # Verify no alternate allele when there is no evidence of variation
        >>> r = pileup.Record(['ID', 42, 'g', 14, 'ggggGGGG...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, None, '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [None], None, [], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='0', SDP=14, RD=14, AD=0, RDF=7, RDR=7, ADF=0, ADR=0, FT='PASS'))
        >>>
        >>> # Verify ALT=. and GT=. when there is no depth
        >>> r = pileup.Record(['ID', 42, 'G', 0, '', ''], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [None], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='.', SDP=0, RD=0, AD=0, RDF=0, RDR=0, ADF=0, ADR=0, FT='Fail'))
        >>>
        >>> # Verify the alternate allele is identified and GT=. when the ref and alt allele have equal depth
        >>> # This test should be run repeatedly. When using python Counters, the most_common sort order is non-deterministic when the counts are equal.
        >>> r = pileup.Record(['ID', 42, 'G', 8, '..,,AAaa', '00001111'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='.', SDP=8, RD=4, AD=[4], RDF=2, RDR=2, ADF=[2], ADR=[2], FT='Fail'))
        >>>
        >>>
        >>> # Verify the alternate alleles are identified and GT=. when the ref and multiple alt alleles have equal depth
        >>> # Verify alt alleles are in deterministic alphabetical order
        >>> # This test should be run repeatedly. When using python Counters, the most_common sort order is non-deterministic when the counts are equal.
        >>> r = pileup.Record(['ID', 42, 'G', 16, '..,,AAaaTTttCCcc', '0000111122223333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, ["Fail"], '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A, C, T], None, ['Fail'], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='.', SDP=16, RD=4, AD=[4, 4, 4], RDF=2, RDR=2, ADF=[2, 2, 2], ADR=[2, 2, 2], FT='Fail'))
        >>>
        >>> # Verify alternate alleles are sorted by frequency, then alphabetical order when there are multiple alt alleles
        >>> r = pileup.Record(['ID', 42, 'G', 23, 'TttaaAAAcCC.......,,,,,', '00011111222333333333333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, None, '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'G', [A, C, T], None, [], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='0', SDP=23, RD=12, AD=[5, 3, 3], RDF=7, RDR=5, ADF=[3, 2, 1], ADR=[2, 1, 2], FT='PASS'))
        >>>
        >>> # Verify lowercase reference is preserved when preserve_ref_case is True
        >>> writer.close()
        >>> writer = SingleSampleWriter("/dev/null", preserve_ref_case=True)
        >>> filters = caller.get_filter_descriptions()
        >>> writer.write_header("dummy-sample-name", filters, "dummy_reference-name")
        >>> r = pileup.Record(['ID', 42, 'g', 14, 'ggggGGGG...,,,', '00001111222333'], 15)
        >>> v = writer._make_vcf_record_from_pileup(r, None, '.')
        >>> v.CHROM, v.POS, v.ID, v.REF, v.ALT, v.QUAL, v.FILTER, v.INFO, v.FORMAT
        ('ID', 42, None, 'g', [None], None, [], {'NS': 1}, 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT')
        >>> v.samples[0]
        Call(sample=None, VcfCallData(GT='0', SDP=14, RD=14, AD=0, RDF=7, RDR=7, ADF=0, ADR=0, FT='PASS'))
        >>>
        >>> writer.close()
        """
        ref = pileup_record.reference_base
        upper_ref = ref.upper()
        if not self.preserve_ref_case:
            ref = upper_ref

        ##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
        ##FORMAT=<ID=SDP,Number=1,Type=Integer,Description="Raw Read Depth">
        ##FORMAT=<ID=RD,Number=1,Type=Integer,Description="Depth of reference-supporting bases (reads1)">
        ##FORMAT=<ID=AD,Number=1,Type=Integer,Description="Depth of variant-supporting bases (reads2)">
        ##FORMAT=<ID=RDF,Number=1,Type=Integer,Description="Depth of reference-supporting bases on forward strand (reads1plus)">
        ##FORMAT=<ID=RDR,Number=1,Type=Integer,Description="Depth of reference-supporting bases on reverse strand (reads1minus)">
        ##FORMAT=<ID=ADF,Number=1,Type=Integer,Description="Depth of variant-supporting bases on forward strand (reads2plus)">
        ##FORMAT=<ID=ADR,Number=1,Type=Integer,Description="Depth of variant-supporting bases on reverse strand (reads2minus)">
        ##FORMAT=<ID=FT,Number=1,Type=String,Description="Genotype filters using the same codes as the FILTER data element">

        if pileup_record.most_common_good_bases is None:  # no good depth
            alt = []
            gt = '.'
            ad = 0
            adf = 0
            adr = 0
        else:
            alt = [base for base in pileup_record.most_common_good_bases if base != upper_ref]
            #alt = alt[0: 1]  # only consider the first alternate allele because PyVCF package crashes when reading comma
            if len(alt) == 0:
                gt = '0'
                ad = 0
                adf = 0
                adr = 0
            else:
                if pileup_record.most_common_good_bases[0] == upper_ref:
                    gt = '0'
                else:
                    gt = '1'
                ad = [pileup_record.base_good_depth[base] for base in alt]
                adf = [pileup_record.forward_base_good_depth[base] for base in alt]
                adr = [pileup_record.reverse_base_good_depth[base] for base in alt]

            if failed_filters:
                if failed_snp_gt == '.':
                    gt = '.'  # missing, unable to make a call
                elif failed_snp_gt == '0':
                    gt = '0'  # reference
                else:
                    gt = '1'  # alt allele

        sdp = pileup_record.raw_depth
        rd = pileup_record.base_good_depth[upper_ref]
        rdf = pileup_record.forward_base_good_depth[upper_ref]
        rdr = pileup_record.reverse_base_good_depth[upper_ref]
        ft = ';'.join(failed_filters) if failed_filters else "PASS"

        #print("Position:", pileup_record.position, "Alt:", alt, gt, sdp, rd, ad, rdf, rdr, adf, adr, ft)
        sample_data = self.VcfCallData(gt, sdp, rd, ad, rdf, rdr, adf, adr, ft)

        # http://pyvcf.readthedocs.org/en/latest/API.html#vcf-model-call
        # vcf.model._Call(site, sample, data)
        call = vcf.model._Call(None, None, sample_data)

        # info_dict contains fields that match our VCF_HEAD info fields
        # this sample has a pileup record at this position, so NS=1
        info_dict = {'NS': 1}

        # Make the list of _AltRecord objects needed for the _Record initializer
        if len(alt) == 0:
            alt = [None] # must be an iterable object
        else:
            alt = [vcf.model._Substitution(base) for base in alt]

        # https://pyvcf.readthedocs.org/en/latest/API.html#vcf-model-record
        # vcf.model._Record(CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO, FORMAT, sample_indexes, samples=None)
        vcf_record = vcf.model._Record(
            pileup_record.chrom,
            pileup_record.position,
            None,  # Id
            ref,
            alt, # Cannot be None, because the _Record initializer will try to iterate over this list
            None, # Qual
            failed_filters or [],
            info_dict,
            self.format_str, # Format
            None, # Sample indexes
            [call]  # Samples
        )
        return vcf_record

    def write_from_pileup(self, pileup_record, failed_filters, failed_snp_gt):
        """
        Write a single VCF record for a single sample from a single pileup
        record.

        Parameters
        ----------
        pileup_record : pileup.Record
            Previously parsed pileup record.
        failed_filters : list of str or None
            List of failed snp filters or None if all filters passed
        failed_snp_gt : str
            Controls the VCF file GT data element when a snp fails filters.  Possible values:
            "." : The GT element will be a dot, indicating unable to make a call (default)
            "0" : The GT element will be 0, indicating the reference base
            "1" : The GT element will be the ALT index of the most commonly occuring base, usually 1

        Examples
        --------
        >>> caller = pileup.ConsensusCaller(0.5, 1, 0, 0.0) # freq, depth, strand_depth, strand_bias
        >>> filters = caller.get_filter_descriptions()
        >>> in_memory_file = StringIO()
        >>> in_memory_file.name = "file.vcf"
        >>> writer = SingleSampleWriter(in_memory_file)
        >>> writer.write_header("SampleName", filters, "RefName")
        >>>
        >>> # Verify ALT=. and GT=. when there is no depth
        >>> r = pileup.Record(['ID', 42, 'G', 0, '', ''], 15)
        >>> writer.write_from_pileup(r, ["Fail"], '.')
        >>> line = _read_last_line(in_memory_file)
        >>> chrom, pos, id, ref, alt, qual, filter, info, format, data = line.split()
        >>> chrom, pos, id, ref, alt, qual, filter, info, format, data
        ('ID', '42', '.', 'G', '.', '.', 'Fail', 'NS=1', 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT', '.:0:0:0:0:0:0:0:Fail')
        >>>
        >>> # Verify alternate allele is identified and called when there is only one alt allele
        >>> r = pileup.Record(['ID', 42, 'G', 14, 'aaaaAAAA...,,,', '00001111222333'], 15)
        >>> writer.write_from_pileup(r, None, '.')
        >>> line = _read_last_line(in_memory_file)
        >>> chrom, pos, id, ref, alt, qual, filter, info, format, data = line.split()
        >>> chrom, pos, id, ref, alt, qual, filter, info, format, data
        ('ID', '42', '.', 'G', 'A', '.', 'PASS', 'NS=1', 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT', '1:14:6:8:3:3:4:4:PASS')
        >>>
        >>> # Verify alternate alleles are sorted by frequency, then alphabetical order when there are multiple alt alleles
        >>> r = pileup.Record(['ID', 42, 'G', 23, 'TttaaAAAcCC.......,,,,,', '00011111222333333333333'], 15)
        >>> writer.write_from_pileup(r, None, '.')
        >>> line = _read_last_line(in_memory_file)
        >>> chrom, pos, id, ref, alt, qual, filter, info, format, data = line.split()
        >>> chrom, pos, id, ref, alt, qual, filter, info, format, data
        ('ID', '42', '.', 'G', 'A,C,T', '.', 'PASS', 'NS=1', 'GT:SDP:RD:AD:RDF:RDR:ADF:ADR:FT', '0:23:12:5,3,3:7:5:3,2,1:2,1,2:PASS')
        """
        # Create the PyVCF record
        vcf_record = self._make_vcf_record_from_pileup(pileup_record, failed_filters, failed_snp_gt)

        # Tell PyVCF to write the record
        self.pyvcf_writer.write_record(vcf_record)


def _read_last_line(stream):
    """Helper function for unit testing to read the last line of a file.
    """
    stream.seek(0)
    for line in stream:
        pass
    return line
