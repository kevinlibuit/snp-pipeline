#!/usr/bin/env python2.7

import unittest
#import snppipeline
import filecmp
import os

import imp
#TODO fix these two lines to make paths relative
snppipeline = imp.load_source('snppipeline', '/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/snppipeline/snppipeline.py')
utils       = imp.load_source('utils', '/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/snppipeline/utils.py')

class Test(unittest.TestCase):
    '''Unit test for snppipeline.'''

    def test_snppipeline_lambda_virus(self):
        """Run snppipeline with synthetic virus example.
        """
        
        args_dict = {
            'maxThread':3,      
            'mainPath':'/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/test/testLambdaVirus/',     #TODO make path relative    
            'Reference':'reference/lambda_virus.fasta',     
            'pathFileName':'path.txt',   
            'snplistFileName':'snplist.txt', 
            'snpmaFileName':'snpma.fasta',
            'bamFileName':'reads.bam',
            'pileupFileName':'reads.pileup',
            'verbose':False,
            'includeReference':True,
            'useOldPileups':False,
            'combinedDepthAcrossSamples':10,
            'alleleFrequencyForFirstALTAllele':1.0,
            'arFlagValue':1.0
        } 
        
        #TODO Add test to insure data for test is in directory specified in args_dict['mainPath'],
        #       if not then tell user what script to run to create such a directory

        snppipeline.run_snp_pipeline(args_dict)
        
        #Compare the files in the two directories whose names are given.
        #Returns three lists of file names: match, mismatch, errors. 
        directory_correct = '/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/test/codeComparisonFiles/testLambdaVirus' #TODO make path relative
        directory_run_result = '/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/test/testLambdaVirus'  #TODO make path relative
        files_to_compare = ['snplist.txt','snpma.fasta','samples/sample1/reads.pileup',
                            'samples/sample2/reads.pileup','samples/sample3/reads.pileup',
                            'samples/sample4/reads.pileup','referenceSNP.fasta']
        match, mismatch, errors =  filecmp.cmpfiles(directory_correct,
                                                    directory_run_result,
                                                    files_to_compare,shallow=False)
        print('Match, Mismatch, Errors: '+str(len(match))+', '+str(len(mismatch))+', '+str(len(errors)))
        print('  Match: ',match)
        print('  Mismatch: ',mismatch)
        print('  Errors: ',errors)
        self.assertEqual(True,len(match)    == len(files_to_compare) and
                              len(mismatch) == 0 and
                              len(errors)   == 0)

        #Remove files generated #TODO make this optional?
        for file_name in files_to_compare:
            os.remove(os.path.join(directory_run_result,file_name)) 

#TODO uncomment the agona test, and maybe make it optional depending on 
#       the availability of the data for running the test?
#    def test_snppipeline_agona(self):
#        """Run snppipeline with agona 5 samples example.
#        """
#
#        args_dict = {
#            'maxThread':8,      
#            'mainPath':'/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/test/testAgonaMOM/',    #TODO make path relative     
#            'Reference':'NC_011149.fasta',     
#            'pathFileName':'path.txt',   
#            'snplistFileName':'snplist.txt', 
#            'snpmaFileName':'snpma.fasta',
#            'bamFileName':'reads.bam',
#            'pileupFileName':'reads.pileup',
#            'verbose':False,
#            'includeReference':True,
#            'useOldPileups':False,
#            'combinedDepthAcrossSamples':10,
#            'alleleFrequencyForFirstALTAllele':1.0,
#            'arFlagValue':1.0
#        } 
#
#        #TODO Add test to insure data for test is in directory specified in args_dict['mainPath'],
#        #       if not then tell user what script to run to create such a directory
#
#        snppipeline.run_snp_pipeline(args_dict)
#        
#        #Compare the files in the two directories whose names are given.
#        #Returns three lists of file names: match, mismatch, errors.
#        directory_correct = '/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/test/codeComparisonFiles/testAgonaMOM'  #TODO make path relative
#        directory_run_result = '/home/hugh.rand/mnt/biob/svn/Biostats/rand/snppipeline/test/testAgonaMOM'  #TODO make path relative
#        files_to_compare = ['snplist.txt',
#                            'snpma.fasta',
#                            'samples/CFSAN_genomes/CFSAN000448/reads.pileup',  
#                            'samples/CFSAN_genomes/CFSAN000449/reads.pileup', 
#                            'samples/CFSAN_genomes/CFSAN000450/reads.pileup',
#                            'samples/SRA_data/ERR178930/reads.pileup',
#                            'samples/SRA_data/ERR178931/reads.pileup',
#                            'referenceSNP.fasta']
#        match, mismatch, errors =  filecmp.cmpfiles(directory_correct,
#                                                    directory_run_result,
#                                                    files_to_compare,shallow=False)
#        print('  Match: ',match)
#        print('  Mismatch: ',mismatch)
#        print('  Errors: ',errors)
#        print('Match, Mismatch, Errors: '+str(len(match))+', '+str(len(mismatch))+', '+str(len(errors)))
#        
#        self.assertEqual(True,len(match)    == len(files_to_compare) and
#                              len(mismatch) == 0 and
#                              len(errors)   == 0)
#        
#        #TODO make this optional?
#        for file_name in files_to_compare:
#            os.remove(os.path.join(directory_run_result,file_name)) 

if __name__ == "__main__":
    unittest.main()


