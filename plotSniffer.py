#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Given a collection of .npz files search for course delays and rates.

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
	print """plotSniffer.py - Given a collection of .npz files generated by "the next 
generation of correlator", search for fringes.

Usage:
plotSniffer.py [OPTIONS] npz [npz [...]]

Options:
-h, --help                  Display this help information
-r, --ref-ant               Reference antenna (default = first antenna)
-b, --baseline              Limit plots to the specified baseline in 'ANT-ANT' 
                            format
-d, --decimate              Frequency decimation factor (default = 1)
-l, --limit                 Limit the data loaded to the first N files
                            (default = -1 = load all)
-y, --y-only                Limit the search on VLA-LWA baselines to the VLA
                            Y pol. only
-e, --delay-window          Delay search window in us (default = -inf,inf 
                            = maximum allowed by spectral resolution)
-a, --rate-window           Rate search window in mHz (default = -inf,inf
                            = maximum allowed by temporal resolution)
-i, --interval              Fringe search interveral in seconds (default = 30)
"""
	
	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseConfig(args):
	config = {}
	# Command line flags - default values
	config['refAnt'] = None
	config['baseline'] = None
	config['freqDecimation'] = 1
	config['lastFile'] = -1
	config['yOnlyVLALWA'] = False
	config['delayWindow'] = [-numpy.inf, numpy.inf]
	config['rateWindow'] = [-numpy.inf, numpy.inf]
	config['interval'] = 30
	config['args'] = []
	
	# Read in and process the command line flags
	try:
		opts, args = getopt.getopt(args, "hr:b:d:l:ya:e:i:", ["help", "ref-ant=", "baseline=", "decimate=", "limit=", "y-only", "delay-window=", "rate-window=", "interval="])
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
		elif opt in ('-b', '--baseline'):
			config['baseline'] = [(int(v0,10),int(v1,10)) for v0,v1 in [v.split('-') for v in value.split(',')]]
		elif opt in ('-d', '--decimate'):
			config['freqDecimation'] = int(value, 10)
		elif opt in ('-l', '--limit'):
			config['lastFile'] = int(value, 10)
		elif opt in ('-y', '--y-only'):
			config['yOnlyVLALWA'] = True
		elif opt in ('-e', '--delay-window'):
			config['delayWindow'] = [float(v) for v in value.split(',', 1)]
		elif opt in ('-a', '--rate-window'):
			config['rateWindow'] = [float(v) for v in value.split(',', 1)]
		elif opt in ('-i', '--interval'):
			config['interval'] = float(value)
		else:
			assert False
			
	# Add in arguments
	config['args'] = args
	
	# Fill the baseline list with the conjugates, if needed
	if config['baseline'] is not None:
		newBaselines = []
		for pair in config['baseline']:
			newBaselines.append( (pair[1],pair[0]) )
		config['baseline'].extend(newBaselines)
		
	# Validate
	if len(config['args']) == 0:
		raise RuntimeError("Must provide at least one .npz file to plot")
	if config['freqDecimation'] <= 0:
		raise RuntimeError("Invalid value for the frequency decimation factor")
	if config['lastFile'] <= 0 and config['lastFile'] != -1:
		raise RuntimeError("Invalid value for the last file to process")
		
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
	refSrc, junk1, junk2, junk3, junk4, antennas = readCorrelatorConfiguration(tempConfig)
	os.unlink(tempConfig)
	
	dataDict.close()
	
	# Make sure the reference antenna is in there
	if config['refAnt'] is None:
		config['refAnt'] = antennas[0].stand.id
	else:
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
	visXX = numpy.zeros((nInt,nBL,nChan), dtype=numpy.complex64)
	if not config['yOnlyVLALWA']:
		visXY = numpy.zeros((nInt,nBL,nChan), dtype=numpy.complex64)
	visYX = numpy.zeros((nInt,nBL,nChan), dtype=numpy.complex64)
	visYY = numpy.zeros((nInt,nBL,nChan), dtype=numpy.complex64)

	for i,filename in enumerate(filenames):
		dataDict = numpy.load(filename)

		tStart = dataDict['tStart']
		
		cvisXX = dataDict['vis1XX'][cross,:]
		cvisXY = dataDict['vis1XY'][cross,:]
		cvisYX = dataDict['vis1YX'][cross,:]
		cvisYY = dataDict['vis1YY'][cross,:]
		
		if config['freqDecimation'] > 1:
			cvisXX.shape = (cvisXX.shape[0], cvisXX.shape[1]/config['freqDecimation'], config['freqDecimation'])
			cvisXX = cvisXX.mean(axis=2)
			cvisXY.shape = (cvisXY.shape[0], cvisXY.shape[1]/config['freqDecimation'], config['freqDecimation'])
			cvisXY = cvisXY.mean(axis=2)
			cvisYX.shape = (cvisYX.shape[0], cvisYX.shape[1]/config['freqDecimation'], config['freqDecimation'])
			cvisYX = cvisYX.mean(axis=2)
			cvisYY.shape = (cvisYY.shape[0], cvisYY.shape[1]/config['freqDecimation'], config['freqDecimation'])
			cvisYY = cvisYY.mean(axis=2)
			
		visXX[i,:,:] = cvisXX
		if not config['yOnlyVLALWA']:		
			visXY[i,:,:] = cvisXY
		visYX[i,:,:] = cvisYX
		visYY[i,:,:] = cvisYY	

		times[i] = tStart
		
		dataDict.close()
			
	print "Got %i files from %s to %s (%.1f s)" % (len(filenames), datetime.utcfromtimestamp(times[0]).strftime("%Y/%m/%d %H:%M:%S"), datetime.utcfromtimestamp(times[-1]).strftime("%Y/%m/%d %H:%M:%S"), (times[-1]-times[0]))

	iTimes = numpy.zeros(nInt-1, dtype=times.dtype)
	for i in xrange(1, len(times)):
		iTimes[i-1] = times[i] - times[i-1]
	print " -> Interval: %.3f +/- %.3f seconds (%.3f to %.3f seconds)" % (robust.mean(iTimes), robust.std(iTimes), iTimes.min(), iTimes.max())
	iSize = int(round(config['interval']/iTimes.mean()))
	print " -> Chunk size is %i intervals (%.3f seconds)" % (iSize, iSize*robust.mean(iTimes))
	iCount = times.size/iSize
	print " -> Working with %i chunks of data" % iCount
	
	print "Number of frequency channels: %i (~%.1f Hz/channel)" % (len(freq), freq[1]-freq[0])

	dTimes = times - times[0]
	refTime = (int(times[0]) / 60) * 60
	
	dMax = 1.0/(freq[1]-freq[0])/4
	dMax = int(dMax*1e6)*1e-6
	if -dMax*1e6 > config['delayWindow'][0]:
		config['delayWindow'][0] = -dMax*1e6
	if dMax*1e6 < config['delayWindow'][1]:
		config['delayWindow'][1] = dMax*1e6
	rMax = 1.0/iTimes.mean()/4
	rMax = int(rMax*1e2)*1e-2
	if -rMax*1e3 > config['rateWindow'][0]:
		config['rateWindow'][0] = -rMax*1e3
	if rMax*1e3 < config['rateWindow'][1]:
		config['rateWindow'][1] = rMax*1e3
		
	dres = 1.0
	nDelays = int((config['delayWindow'][1]-config['delayWindow'][0])/dres)
	while nDelays < 50:
		dres /= 10
		nDelays = int((config['delayWindow'][1]-config['delayWindow'][0])/dres)
	while nDelays > 5000:
		dres *= 10
		nDelays = int((config['delayWindow'][1]-config['delayWindow'][0])/dres)
	nDelays += (nDelays + 1) % 2
	
	rres = 10.0
	nRates = int((config['rateWindow'][1]-config['rateWindow'][0])/rres)
	while nRates < 50:
		rres /= 10
		nRates = int((config['rateWindow'][1]-config['rateWindow'][0])/rres)
	while nRates > 5000:
		rres *= 10
		nRates = int((config['rateWindow'][1]-config['rateWindow'][0])/rres)
	nRates += (nRates + 1) % 2
	
	print "Searching delays %.1f to %.1f us in steps of %.2f us" % (config['delayWindow'][0], config['delayWindow'][1], dres)
	print "           rates %.1f to %.1f mHz in steps of %.2f mHz" % (config['rateWindow'][0], config['rateWindow'][1], rres)
	print " "
	
	delay = numpy.linspace(config['delayWindow'][0]*1e-6, config['delayWindow'][1]*1e-6, nDelays)		# s
	drate = numpy.linspace(config['rateWindow'][0]*1e-3,  config['rateWindow'][1]*1e-3,  nRates )		# Hz
	
	# Find RFI and trim it out.  This is done by computing average visibility 
	# amplitudes (a "spectrum") and running a median filter in frequency to extract
	# the bandpass.  After the spectrum has been bandpassed, 3sigma features are 
	# trimmed.  Additionally, area where the bandpass fall below 10% of its mean
	# value are also masked.
	spec  = numpy.median(numpy.abs(visXX.mean(axis=0)), axis=0)
	spec += numpy.median(numpy.abs(visYY.mean(axis=0)), axis=0)
	smth = spec*0.0
	winSize = int(250e3/(freq[1]-freq[0]))
	winSize += ((winSize+1)%2)
	for i in xrange(smth.size):
		mn = max([0, i-winSize/2])
		mx = min([i+winSize, smth.size])
		smth[i] = numpy.median(spec[mn:mx])
	smth /= robust.mean(smth)
	bp = spec / smth
	good = numpy.where( (smth > 0.1) & (numpy.abs(bp-robust.mean(bp)) < 3*robust.std(bp)) )[0]
	nBad = nChan - len(good)
	print "Masking %i of %i channels (%.1f%%)" % (nBad, nChan, 100.0*nBad/nChan)
	
	freq2 = freq*1.0
	freq2.shape += (1,)
	
	dirName = os.path.basename( os.path.dirname(filenames[0]) )
	for b in xrange(len(bls)):
		## Skip over baselines that are not in the baseline list (if provided)
		if config['baseline'] is not None:
			if bls[b] not in config['baseline']:
				continue
		## Skip over baselines that don't include the reference antenna
		elif bls[b][0] != config['refAnt'] and bls[b][1] != config['refAnt']:
			continue
			
		## Check and see if we need to conjugate the visibility, i.e., switch from
		## baseline (*,ref) to baseline (ref,*)
		doConj = False
		if bls[b][1] == config['refAnt']:
			doConj = True
			
		## Figure out which polarizations to process
		if bls[b][0] not in (51, 52) and bls[b][1] not in (51, 52):
			### Standard VLA-VLA baseline
			polToUse = ('XX', 'YY')
			visToUse = (visXX, visYY)
		else:
			### LWA-LWA or LWA-VLA baseline
			if config['yOnlyVLALWA']:
				polToUse = ('YX', 'YY')
				visToUse = (visYX, visYY)
			else:
				polToUse = ('XX', 'XY', 'YX', 'YY')
				visToUse = (visXX, visXY, visYX, visYY)
				
		blName = bls[b]
		if doConj:
			blName = (bls[b][1],bls[b][0])
		blName = '%s-%s' % ('EA%02i' % blName[0] if blName[0] < 51 else 'LWA%i' % (blName[0]-50), 
						'EA%02i' % blName[1] if blName[1] < 51 else 'LWA%i' % (blName[1]-50))
						
		fig = plt.figure()
		fig.suptitle('%s @ %s' % (blName, refSrc.name))
		fig.subplots_adjust(hspace=0.001)
		axR = fig.add_subplot(4, 1, 1)
		axD = fig.add_subplot(4, 1, 2, sharex=axR)
		axP = fig.add_subplot(4, 1, 3, sharex=axR)
		axA = fig.add_subplot(4, 1, 4, sharex=axR)
		markers = {'XX':'s', 'YY':'o', 'XY':'v', 'YX':'^'}
		
		for pol,vis in zip(polToUse, visToUse):
			for i in xrange(iCount):
				subStart, subStop = times[iSize*i], times[iSize*(i+1)-1]
				if (subStop - subStart) > 1.1*config['interval']:
					continue
					
				subTime = times[iSize*i:iSize*(i+1)].mean()
				dTimes2 = dTimes[iSize*i:iSize*(i+1)]*1.0
				dTimes2.shape += (1,)
				subData = vis[iSize*i:iSize*(i+1),b,good]*1.0
				subPhase = vis[iSize*i:iSize*(i+1),b,good]*1.0
				if doConj:
					subData = subData.conj()
					subPhase = subPhase.conj()
				subData = numpy.dot(subData, numpy.exp(-2j*numpy.pi*freq2[good,:]*delay))
				subData /= freq2[good,:].size
				amp = numpy.dot(subData.T, numpy.exp(-2j*numpy.pi*dTimes2*drate))
				amp = numpy.abs(amp / dTimes2.size)
				
				subPhase = numpy.angle(subPhase.mean()) * 180/numpy.pi
				subPhase %= 360
				if subPhase > 180:
					subPhase -= 360
					
				best = numpy.where( amp == amp.max() )
				if amp.max() > 0:
					bsnr = (amp[best]-amp.mean())[0]/amp.std()
					bdly = delay[best[0][0]]*1e6
					brat = drate[best[1][0]]*1e3
					
					axR.plot(subTime-refTime, brat, linestyle='', marker=markers[pol], color='k')
					axD.plot(subTime-refTime, bdly, linestyle='', marker=markers[pol], color='k')
					axP.plot(subTime-refTime, subPhase, linestyle='', marker=markers[pol], color='k')
					axA.plot(subTime-refTime, amp.max()*1e3, linestyle='', marker=markers[pol], color='k', label=pol)
					
		# Legend and reference marks
		handles, labels = axA.get_legend_handles_labels()
		axA.legend(handles[::iCount], labels[::iCount], loc=0)
		oldLim = axR.get_xlim()
		for ax in (axR, axD, axP):
			ax.hlines(0, oldLim[0], oldLim[1], linestyle=':', alpha=0.5)
		axR.set_xlim(oldLim)
		# Turn off redundant x-axis tick labels
		xticklabels = axR.get_xticklabels() + axD.get_xticklabels() + axP.get_xticklabels()
		plt.setp(xticklabels, visible=False)
		for ax in (axR, axD, axP, axA):
			ax.set_xlabel('Elapsed Time [s since %s]' % datetime.utcfromtimestamp(refTime).strftime('%Y%b%d %H:%M'))
		# Flip the y axis tick labels on every other plot
		for ax in (axR, axP):
			ax.yaxis.set_label_position('right')
			ax.tick_params(axis='y', which='both', labelleft='off', labelright='on')
		# Get the labels
		axR.set_ylabel('Rate [mHz]')
		axD.set_ylabel('Delay [$\\mu$s]')
		axP.set_ylabel('Phase [$^\\circ$]')
		axA.set_ylabel('Amp.$\\times10^3$')
		# Set the y ranges
		axR.set_ylim((-max([abs(v) for v in axR.get_ylim()]), max([abs(v) for v in axR.get_ylim()])))
		axD.set_ylim((-max([abs(v) for v in axD.get_ylim()]), max([abs(v) for v in axD.get_ylim()])))
		ax.set_ylim((-180,180))
		axA.set_ylim((0,axA.get_ylim()[1]))
		plt.draw()
		
	plt.show()


if __name__ == "__main__":
	main(sys.argv[1:])
	
