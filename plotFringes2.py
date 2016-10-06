#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
A fancier version of plotFringes.py that makes waterfall-like plots from .npz
files created by the next generation of correlator.

$Rev$
$LastChangedBy$
$LastChangedDate$
"""

import os
import sys
import glob
import numpy
import getopt
import tempfile
from datetime import datetime

from lsl.statistics import robust
from lsl.misc.mathutil import to_dB

from utils import readCorrelatorConfiguration

from matplotlib import pyplot as plt


def usage(exitCode=None):
	print """plotFringes2.py - Given a collection of .npz files generated by "the next 
generation of correlator", create plots of the visibilities

Usage:
plotFringes2.py [OPTIONS] npz [npz [...]]

Options:
-h, --help                  Display this help information
-r, --ref-ant               Limit plots to baselines containing the reference 
                            antenna (default = plot everything)
-x, --xx                    Plot XX data (default)
-z, --xy                    Plot XY data
-w, --yx                    Plot YX data
-y, --yy                    Plot YY data
-l, --limit                 Limit the data loaded to the first N files
                            (default = -1 = load all)
-d, --decimate              Frequency decimation factor (default = 1)
"""
	
	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseConfig(args):
	config = {}
	# Command line flags - default values
	config['refAnt'] = None
	config['polToPlot'] = 'XX'
	config['lastFile'] = -1
	config['freqDecimation'] = 1
	config['args'] = []
	
	# Read in and process the command line flags
	try:
		opts, args = getopt.getopt(args, "hr:xzwyl:d:", ["help", "ref-ant=", "xx", "xy", "yx", "yy", "limit=", "decimate="])
	except getopt.GetoptError, err:
		# Print help information and exit:
		print str(err) # will print something like "option -a not recognized"
		usage(exitCode=2)
		
	# Work through opts
	for opt, value in opts:
		if opt in ('-h', '--help'):
			usage(exitCode=0)
		elif opt in ('-r', '--ref-ant'):
			config['refAnt'] = int(value, 10)
		elif opt in ('-x', '--xx'):
			config['polToPlot'] = 'XX'
		elif opt in ('-z', '--xy'):
			config['polToPlot'] = 'XY'
		elif opt in ('-w', '--yx'):
			config['polToPlot'] = 'YX'
		elif opt in ('-y', '--yy'):
			config['polToPlot'] = 'YY'
		elif opt in ('-l', '--limit'):
			config['lastFile'] = int(value, 10)
		elif opt in ('-d', '--decimate'):
			config['freqDecimation'] = int(value, 10)
		else:
			assert False
			
	# Add in arguments
	config['args'] = args
	
	# Validate
	if len(config['args']) == 0:
		raise RuntimeError("Must provide at least one .npz file to plot")
	if config['lastFile'] <= 0 and config['lastFile'] != -1:
		raise RuntimeError("Invalid value for the last file to plot")
		
	# Return configuration
	return config


def main(args):
	# Parse the command line
	config = parseConfig(args)

	filenames = config['args']
	filenames.sort()
	if config['lastFile'] != -1:
		filenames = filenames[:config['lastFile']]
		
	nInt = len(filenames)
	
	dataDict = numpy.load(filenames[0])
	tInt = dataDict['tInt']
	nBL, nChan = dataDict['vis1XX'].shape
	freq = dataDict['freq1']
	
	cConfig = dataDict['config']
	fh, tempConfig = tempfile.mkstemp(suffix='.txt', prefix='config-')
	fh = open(tempConfig, 'w')
	for line in cConfig:
		fh.write('%s\n' % line)
	fh.close()
	refSrc, junk1, junk2, junk3, antennas = readCorrelatorConfiguration(tempConfig)
	os.unlink(tempConfig)
	
	dataDict.close()
	
	# Make sure the reference antenna is in there
	if config['refAnt'] is not None:
		found = False
		for ant in antennas:
			if ant.stand.id == config['refAnt']:
				found = True
				break
		if not found:
			raise RuntimeError("Cannot file reference antenna %i in the data" % config['refAnt'])
			
	bls = []
	l = 0
	cross = []
	for i in xrange(0, len(antennas), 2):
		ant1 = antennas[i].stand.id
		for j in xrange(i, len(antennas), 2):
			ant2 = antennas[j].stand.id
			if ant1 != ant2:
				if config['refAnt'] is None:
					bls.append( (ant1,ant2) )
					cross.append( l )
				else:
					if ant1 == config['refAnt'] or ant2 == config['refAnt']:
						bls.append( (ant1,ant2) )
						cross.append( l )
			l += 1
	nBL = len(cross)
	
	if config['freqDecimation'] > 1:
		if nChan % config['freqDecimation'] != 0:
			raise RuntimeError("Invalid freqeunce decimation factor:  %i %% %i = %i" % (nChan, config['freqDecimation'], nChan%config['freqDecimation']))

		nChan /= config['freqDecimation']
		freq.shape = (freq.size/config['freqDecimation'], config['freqDecimation'])
		freq = freq.mean(axis=1)
		
	times = numpy.zeros(nInt, dtype=numpy.float64)
	visToPlot = numpy.zeros((nInt,nBL,nChan), dtype=numpy.complex64)
	
	for i,filename in enumerate(filenames):
		dataDict = numpy.load(filename)

		tStart = dataDict['tStart']
		
		cvis = dataDict['vis1%s' % config['polToPlot']][cross,:]
		if config['freqDecimation'] > 1:
			cvis.shape = (cvis.shape[0], cvis.shape[1]/config['freqDecimation'], config['freqDecimation'])
			cvis = cvis.mean(axis=2)
			
		visToPlot[i,:,:] = cvis
		
		times[i] = tStart
		
		dataDict.close()
			
	print "Got %i files from %s to %s (%.1f s)" % (len(filenames), datetime.utcfromtimestamp(times[0]).strftime("%Y/%m/%d %H:%M:%S"), datetime.utcfromtimestamp(times[-1]).strftime("%Y/%m/%d %H:%M:%S"), (times[-1]-times[0]))

	iTimes = numpy.zeros(nInt-1, dtype=times.dtype)
	for i in xrange(1, len(times)):
		iTimes[i-1] = times[i] - times[i-1]
	print " -> Interval: %.3f +/- %.3f seconds (%.3f to %.3f seconds)" % (iTimes.mean(), iTimes.std(), iTimes.min(), iTimes.max())
	
	print "Number of frequency channels: %i (~%.1f Hz/channel)" % (len(freq), freq[1]-freq[0])

	dTimes = times - times[0]
	
	delay = numpy.linspace(-350e-6, 350e-6, 301)		# s
	drate = numpy.linspace(-150e-3, 150e-3, 301)		# Hz
	
	good = numpy.where( (freq>72e6) & ((freq<77.26e6) | (freq>77.3e6)) & ((freq<76.3e6) | (freq>76.32e6)) & ((freq<76.82e6) | (freq>76.83e6)) & ((freq<78.8e6) | (freq>76.86e6)) & ((freq<79.85e6) | (freq>79.90e6)) )[0]
	
	fig1 = plt.figure()
	fig2 = plt.figure()
	fig3 = plt.figure()
	fig4 = plt.figure()
	
	k = 0
	nRow = int(numpy.sqrt( len(bls) ))
	nCol = int(numpy.ceil(len(bls)*1.0/nRow))
	for b in xrange(len(bls)):
		i,j = bls[b]
		vis = visToPlot[:,b,:]
		
		ax = fig1.add_subplot(nRow, nCol, k+1)
		ax.imshow(numpy.angle(vis), extent=(freq[0], freq[-1], dTimes[0], dTimes[-1]), origin='lower', vmin=-numpy.pi, vmax=numpy.pi, interpolation='nearest')
		ax.axis('auto')
		ax.set_xlabel('Frequency [MHz]')
		ax.set_ylabel('Elapsed Time [s]')
		ax.set_title("%i,%i - %s" % (i,j,config['polToPlot']))
		
		ax = fig2.add_subplot(nRow, nCol, k+1)
		ax.imshow( numpy.log10(numpy.abs(vis))*10, extent=(freq[0], freq[-1], dTimes[0], dTimes[-1]), origin='lower', interpolation='nearest')
		ax.axis('auto')
		ax.set_xlabel('Frequency [MHz]')
		ax.set_ylabel('Elapsed Time [s]')
		ax.set_title("%i,%i - %s" % (i,j,config['polToPlot']))
		
		ax = fig3.add_subplot(nRow, nCol, k+1)
		ax.plot(freq/1e6, numpy.log10(numpy.abs(vis).mean(axis=0))*10)
		ax.set_xlabel('Frequency [MHz]')
		ax.set_ylabel('Mean Vis. Amp. [dB]')
		ax.set_title("%i,%i - %s" % (i,j,config['polToPlot']))
		
		ax = fig4.add_subplot(nRow, nCol, k+1)
		ax.plot(dTimes, numpy.angle(vis[:,good].mean(axis=1)))
		ax.set_ylim((-numpy.pi,numpy.pi))
		ax.set_xlabel('Elapsed Time [s]')
		ax.set_ylabel('Mean Vis. Phase [rad]')
		ax.set_title("%i,%i - %s" % (i,j,config['polToPlot']))
		
		k += 1
		
	fig1.suptitle("%s to %s UTC" % (datetime.utcfromtimestamp(times[0]).strftime("%Y/%m/%d %H:%M"), datetime.utcfromtimestamp(times[-1]).strftime("%Y/%m/%d %H:%M")))
	fig2.suptitle("%s to %s UTC" % (datetime.utcfromtimestamp(times[0]).strftime("%Y/%m/%d %H:%M"), datetime.utcfromtimestamp(times[-1]).strftime("%Y/%m/%d %H:%M")))
	fig3.suptitle("%s to %s UTC" % (datetime.utcfromtimestamp(times[0]).strftime("%Y/%m/%d %H:%M"), datetime.utcfromtimestamp(times[-1]).strftime("%Y/%m/%d %H:%M")))
	fig4.suptitle("%s to %s UTC" % (datetime.utcfromtimestamp(times[0]).strftime("%Y/%m/%d %H:%M"), datetime.utcfromtimestamp(times[-1]).strftime("%Y/%m/%d %H:%M")))
	
	plt.show()


if __name__ == "__main__":
	main(sys.argv[1:])
