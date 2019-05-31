import pylab
import pickle
import os


def getTarget0err(f):
  stdin,stdout = os.popen2("tail -n 4 "+f)
  stdin.close()
  lines = stdout.readlines(); stdout.close()
  line = lines[0].split()
  return float(line[5])

def errorFromShell(filestem, readTarget0ErrFromRunFile, maxGens, maxCands, maxTargets):

    minVal = 1
    minValtarg0 = 1
    for igen in range(maxGens):
            for icand in range(maxCands):
                    error = []
                    for itarget in range(maxTargets):
                            try:
                                    errfilename = '%s/gen_%s_cand_%d_target_%d_error' % (filestem,igen,icand,itarget)
                                    runfilename = '%s/gen_%s_cand_%d.run' % (filestem,igen,icand)
                                    with open(errfilename, 'r') as f:
                                            error.append(pickle.load(f))
                                            print 'gen=%d, cand=%d, target=%d: error = %f' % (igen, icand, itarget, error[-1])
                            except:
                                    print('not found file: stem=%s, gen=%d, cand=%d, targ=%d' % (filestem,igen,icand,itarget))
                    avgErr = pylab.mean(error)
                    if readTarget0ErrFromRunFile:
                            try:
                                    target0err = getTarget0err(runfilename)
                                    print "error target 0: %.2f \n" % (target0err)  
                                    if target0err < minValtarg0:
                                            minValtarg0 = target0err
                                            minCandtarg0 = icand
                                            minGentarg0 = igen     
                            except:       
                                    print "error reading file:", runfilename        

                    print "avg error: %.2f \n" % (avgErr)
                    if avgErr < minVal:
                            minVal = avgErr
                            minCand = icand
                            minGen = igen

    print "Min error = %f ; gen = %d ; cand = %d \n" % (minVal, minGen, minCand)
    if readTarget0ErrFromRunFile: 
            print "Min error (target 0) = %f ; gen = %d ; cand = %d \n" % (minValtarg0, minGentarg0, minCandtarg0)

def errorFromPickle(filestem, maxGens, maxCands):
    from collections import OrderedDict
    minVals = OrderedDict
    minVals = {'error0_pre': [1,0,0], 'error1_pre': [1,0,0], 'error_pre': [1,0,0], 'errord_pre': [1,0,0], \
        'error0_post': [1,0,0], 'error1_post': [1,0,0], 'error_post': [1,0,0], 'errord_post': [1,0,0], \
        'error0_lesion': [1,0,0], 'error1_lesion': [1,0,0], 'error_pre': [1,0,0], 'errord_tot': [1,0,0], 'error_fitness': [1,0,0]}
    
    for igen in range(maxGens):
        for icand in range(maxCands):
            error = []
            try:
                errfilename = '%s/gen_%d_cand_%d_target_0_error' % (filestem,igen,icand)
                with open(errfilename, 'r') as f:
                        error = pickle.load(f)
                        #print 'gen=%d, cand=%d, errord_tot = %f, error_fitness = %f' % (igen, icand, error['errord_tot'], error['error_fitness'])
                for key,val in error.iteritems():
                    if val < minVals[key][0]: 
                        minVals[key][0] = val
                        minVals[key][1] = igen
                        minVals[key][2] = icand
            except:
                    print('not found file: stem=%s, gen=%d, cand=%d' % (filestem,igen,icand))

    for key,val in minVals.iteritems():
        print "%s = %f ; gen = %d ; cand = %d \n" % (key, val[0], val[1], val[2])
   
   

# set params
filestem = '../data/15aug29_evolutionStrategy'
maxGens = 540
maxCands = 40
maxTargets = 1
readTarget0ErrFromRunFile = 1

# call function to obtain errors from shell output
#errorFromShell(filestem, readTarget0ErrFromRunFile, maxGens, maxCands, maxTargets)

# call function to obtain errors from pickle file
errorFromPickle(filestem, maxGens, maxCands)


