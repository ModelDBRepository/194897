"""
MODEL

A large-scale network simulation for exploring traveling waves, stimuli,
and STDs. Built solely in Python, using Izhikevich neurons and with MPI
support. Runs in real-time with over 8000 cells when appropriately
parallelized.
M1 model extended to interface with Plexon-recorded PMd data, virtual arm,
and reinforcement learning

Usage:
    python model.py # Run simulation, optionally plot a raster
    python simmovie.py # Show a movie of the results
    python model.py scale=20 # Run simulation, set scale=20

MPI usage:
    mpiexec -n 4 nrniv -python -mpi model.py

Version: 2014feb21 by cliffk
2014sep19 modified by salvadord and giljael
"""


###############################################################################
### IMPORT MODULES
###############################################################################

from pylab import seed, rand, sqrt, exp, transpose, ceil, concatenate, array, zeros, ones, vstack, show, disp, mean, inf, concatenate, unique, delete
from time import time, sleep
from datetime import datetime
from scipy.io import savemat, loadmat 
import pickle

from neuron import h, init, run # Import NEURON
import shared as s # Import all shared variables and parameters
import analysis
from arm import Arm # Class with arm methods and variables


###############################################################################
### Sequences of commands to run full model
###############################################################################

# training and testing to 2 targets manually
def runTrainTest2targets():

    # optimized values for musculoskeletal arm (here using dummy arm for demo purposes) 
    s.targetid = 0
    s.trainTime = 2000 # 85000 # using 2 sec for demo purposes
    s.stdpwin = 48.5 
    s.eligwin = 117.8 
    s.RLfactor = 0.01 #6
    s.RLinterval = 76.8
    s.backgroundrate = s.backgroundrateTest = 134.5 
    s.backgroundrateExplor = 5
    s.cmdmaxrate = 528.8 
    s.PMdconnweight = 1.0
    s.PMdconnprob = 2.4

    s.useArm = 'dummyArm' #'musculoskeletal'

    s.numTrials = ceil(s.trainTime/1000)
    s.trialTargets = [i%2 for i in range(int(s.numTrials+1))] # set target for each trial
    s.targetid=s.trialTargets[0]
  
    verystart=time() # store initial time

    s.plotraster = 1 # set plotting params
    s.plotconn = 0
    s.plotweightchanges = 0
    s.plot3darch = 0
    s.graphsArm = 1
    s.animArm = 1
    s.savemat = 0 # save data during testing
    s.armMinimalSave = 1 # save only arm related data

    # initialize network
    createNetwork() 
    addStimulation()
    addBackground()

    # train
    s.usestdp = 1 # Whether or not to use STDP
    s.useRL = 0 # Where or not to use RL
    s.explorMovs = 1# enable exploratory movements
    s.antagInh = 0 # enable exploratory movements
    s.duration = s.trainTime # train time

    setupSim()
    runSim()
    finalizeSim()
    #saveData()
    plotData()

    # test target 0
    s.backgroundrate=s.backgroundrateTest # 300
    s.cmdmaxrate=s.cmdmaxrateTest # 15
    addBackground()
    s.usestdp = 0 # Whether or not to use STDP
    s.useRL = 0 # Where or not to use RL
    s.explorMovs = 0 # disable exploratory movements
    s.duration = s.testTime # testing time
    s.armMinimalSave = 0 # save only arm related data
    
    s.targetid = 0
    setupSim()
    runSim()
    finalizeSim()
    #saveData()
    plotData()

    if s.rank == 0: # save error to file
        error0 = mean(s.arm.errorAll)
        print 'Target error for target ',s.targetid,' is:', error0 
        s.arm.plotTraj(s.outfilestem+'_t0.png') 

    # test target 1
    s.targetid = 1
    setupSim()
    runSim()
    finalizeSim()
    saveData()
    plotData()

    if s.rank == 0: # save error to file
        error1 = mean(s.arm.errorAll)
        print 'Target error for target 0=', error0, '; target 1=', error1 
        s.arm.plotTraj(s.outfilestem+'_t1.png') 

        errorMean = (error0+error1)/2
        errorFitness = errorMean + abs(error0-error1)  # fitness penalizes difference between target errors
        errorDic = {}
        errorDic['error0'] = error0
        errorDic['error1'] = error1
        errorDic['meanError'] = errorMean
        errorDic['errorFitness'] = errorFitness
        
        print 'Mean error = %.4f ; Mean error + difference (fitness) = %.4f'%(errorMean, errorFitness)

        s.targetid = 0 # so saves to correct file name (error of both targets saved to single file ending in target_0_error)
        with open('%s_target_%d_error'% (s.outfilestem,s.targetid), 'w') as f: # save avg error over targets to outfilestem
            pickle.dump(errorDic, f)

    ## Wrapping up
    s.pc.runworker() # MPI: Start simulations running on each host
    s.pc.done() # MPI: Close MPI
    totaltime = time()-verystart # See how long it took in total
    print('\nDone; total time = %0.1f s.' % totaltime)
    if (s.plotraster==False and s.plotconn==False and s.plotweightchanges==False): h.quit() # Quit extra processes, or everything if plotting wasn't requested (since assume non-interactive)


# training and testing to 2 targets via evolutionary optim algorithm (batch, no graphics)
def runTrainTest2targetsOptim():
    # evol optimizes the following:
    s.RLrates = s.RLfactor*array([[0.25, -0.25], [0.0, 0.0]]) # RL potentiation/depression rates for E->anything and I->anything, e.g. [0,:] is pot/dep for E cells
    s.connprobs[s.PMd,s.ER5]=s.PMdconnprob
    s.connweights[s.PMd,s.ER5,s.AMPA]=s.PMdconnweight

    s.verbose=0
    s.useArm = 'musculoskeletal'
    #s.useArm = 'dummyArm'
    s.numTrials = ceil(s.trainTime/1000)
    s.trialTargets = [i%2 for i in range(int(s.numTrials+1))] # set target for each trial
    s.targetid=s.trialTargets[0]
  
    verystart=time() # store initial time

    s.plotraster = 0 # set plotting params
    s.plotconn = 0
    s.plotweightchanges = 0
    s.plot3darch = 0
    s.graphsArm = 0
    s.animArm = 0
    s.savemat = 0 # save data during testing
    s.armMinimalSave = 0 # save only arm related data

    # train
    s.usestdp = 1 # Whether or not to use STDP
    s.useRL = 1 # Where or not to use RL
    s.explorMovs = 1 # enable exploratory movements
    s.antagInh = 0 # enable exploratory movements
    s.duration = s.trainTime # train time
    s.timebetweensaves =  s.trainTime - 1000

    # initialize network
    createNetwork() 
    addStimulation()
    addBackground()

    # run train
    setupSim()
    runSim()
    finalizeSim()
    #saveData()
    #plotData()
    if s.rank == 0: # save png of traj
        s.arm.plotTraj(s.outfilestem+'_train.png')  # save traj fig to file 
        analysis.plotweightchanges(s.outfilestem+'_train_weights.png')

    test = 1
    s.savemat = 1
    if test:
        # test target 0
        #s.backgroundrate=s.backgroundrateTest # 300
        #s.cmdmaxrate=s.cmdmaxrateTest # 15
        addBackground()
        s.usestdp = 0 # Whether or not to use STDP
        s.useRL = 0 # Where or not to use RL
        s.explorMovs = 0 # disable exploratory movements
        s.duration = s.testTime # testing time
        s.armMinimalSave = 0 # save only arm related data
        
        s.targetid = 0
        setupSim()
        runSim()
        finalizeSim()
        saveData()
        #plotData()

        if s.rank == 0: # save error to file
            error0 = mean(s.arm.errorAll)
            print 'Target error for target ',s.targetid,' is:', error0 
            s.arm.plotTraj(s.outfilestem+'_t0.png') 
            analysis.plotraster(s.outfilestem+'_t0_raster.png')

        # test target 1
        s.targetid = 1
        setupSim()
        runSim()
        finalizeSim()
        saveData()
        #plotData()

        if s.rank == 0: # save error to file
            error1 = mean(s.arm.errorAll)
            print 'Target error for target 0=', error0, '; target 1=', error1 
            s.arm.plotTraj(s.outfilestem+'_t1.png') 
            analysis.plotraster(s.outfilestem+'_t1_raster.png')

            errorMean = (error0+error1)/2
            errorFitness = errorMean + abs(error0-error1)  # fitness penalizes difference between target errors
            errorDic = {}
            errorDic['error0'] = error0
            errorDic['error1'] = error1
            errorDic['meanError'] = errorMean
            errorDic['errorFitness'] = errorFitness
            
            print 'Mean error = %.4f ; Mean error + difference (fitness) = %.4f'%(errorMean, errorFitness)

            s.targetid = 0 # so saves to correct file name (error of both targets saved to single file ending in target_0_error)
            with open('%s_target_%d_error'% (s.outfilestem,s.targetid), 'w') as f: # save avg error over targets to outfilestem
                pickle.dump(errorDic, f)

    ## Wrapping up
    s.pc.runworker() # MPI: Start simulations running on each host
    s.pc.done() # MPI: Close MPI
    totaltime = time()-verystart # See how long it took in total
    print('\nDone; total time = %0.1f s.' % totaltime)
    if (s.plotraster==False and s.plotconn==False and s.plotweightchanges==False): h.quit() # Quit extra processes, or everything if plotting wasn't requested (since assume non-interactive)


###############################################################################
### Create Network
###############################################################################

def createNetwork():
    ## Print diagnostic information
    if s.rank==0: print("\nCreating simulation of %i cells for %0.1f s on %i hosts..." % (sum(s.popnumbers),s.duration/1000.,s.nhosts)) 
    s.pc.barrier()
    
    ## Create empty data structures
    s.cells=[] # Create empty list for storing cells
    s.dummies=[] # Create empty list for storing fake sections
    s.gidVec=[] # Empty list for storing GIDs (index = local id; value = gid)
    s.gidDic = {} # Empyt dict for storing GIDs (key = gid; value = local id) -- ~x6 faster than gidVec.index()
    

    ## Set cell types
    celltypes=[]
    for c in range(s.ncells): # Loop over each cell. ncells is all cells in the network.
        if s.cellclasses[c]==1: celltypes.append(s.RS) # Append a regular spiking pyramidal cell
        elif s.cellclasses[c]==2: celltypes.append(s.IB) # Append an intrinsically bursting pyramidal cell
        elif s.cellclasses[c]==3: celltypes.append(s.CH) # Append a chattering cell
        elif s.cellclasses[c]==4: celltypes.append(s.LTS) # Append a low-threshold spiking interneuron
        elif s.cellclasses[c]==5: celltypes.append(s.FS) # Append a fast-spiking interneuron
        elif s.cellclasses[c]==4: celltypes.append(s.TC) # Append a thalamocortical cell
        elif s.cellclasses[c]==5: celltypes.append(s.RTN) # Append a reticular thalamic nucleus cell
        elif s.cellclasses[c]==-1: celltypes.append(s.nsloc) # Append a nsloc
        else: raise Exception('Undefined cell class "%s"' % s.cellclasses[c]) # No match? Cause an error


    ## Set positions
    seed(s.id32('%d'%s.randseed)) # Reset random number generator
    s.xlocs = s.modelsize*rand(s.ncells) # Create random x locations
    s.ylocs = s.modelsize*rand(s.ncells) # Create random y locations
    s.zlocs = rand(s.ncells) # Create random z locations
    for c in range(s.ncells): 
        s.zlocs[c] = s.corticalthick * (s.zlocs[c]*(s.popyfrac[s.cellpops[c]][1]-s.popyfrac[s.cellpops[c]][0]) + s.popyfrac[s.cellpops[c]][0])  # calculate based on yfrac for population and corticalthick 


    ## Actually create the cells
    s.spikerecorders = [] # Empty list for storing spike-recording Netcons
    s.hostspikevecs = [] # Empty list for storing host-specific spike vectors
    s.cellsperhost = 0
    if s.PMdinput == 'Plexon': ninnclDic = len(s.innclDic) # number of PMd created in this worker
    for c in xrange(int(s.rank), s.ncells, s.nhosts):
        s.dummies.append(h.Section()) # Create fake sections
        gid = c
        if s.cellnames[gid] == 'PMd':
            if s.PMdinput == 'Plexon':
                cell = celltypes[gid](cellid = gid) # create an NSLOC
                s.inncl.append(h.NetCon(None, cell))  # This netcon receives external spikes
                s.innclDic[gid - s.ncells - s.server.numPMd] = ninnclDic # This dictionary works in case that PMd's gid starts from 0.
                ninnclDic += 1
            elif s.PMdinput == 'targetSplit':
                cell = celltypes[gid](cellid = gid) # create an NSLOC
                cell.number = s.backgroundnumber
                cell.interval = s.backgroundrateMin**-1*1e3
                cell.noise = s.PMdNoiseRatio
            elif s.PMdinput == 'spikes':
                cell = h.VecStim()
            else:
                cell = celltypes[gid](cellid = gid) # create an NSLOC
                cell.number = s.backgroundnumber
                cell.interval = s.backgroundrateMin**-1*1e3
                
        elif s.cellnames[gid] == 'ASC':
            cell = celltypes[gid](cellid = gid) #create an NSLOC    
        else: 
            if s.cellclasses[gid]==3: 
                cell = s.fastspiking(s.dummies[s.cellsperhost], vt=-47, cellid=gid) # Don't use LTS cell, but instead a FS cell with a low threshold
            else: 
                cell = celltypes[gid](s.dummies[s.cellsperhost], cellid=gid) # Create a new cell of the appropriate type (celltypes[gid]) and store it
            #if s.verbose>0: s.cells[-1].useverbose(s.verbose, s.filename+'los.txt') # Turn on diagnostic to file
        s.cells.append(cell) 
        s.gidVec.append(gid) # index = local id; value = global id
        s.gidDic[gid] = s.cellsperhost # key = global id; value = local id -- used to get local id because gid.index() too slow!
        s.pc.set_gid2node(gid, s.rank)

        spikevec = h.Vector()
        s.hostspikevecs.append(spikevec)
        spikerecorder = h.NetCon(cell, None)
        spikerecorder.record(spikevec)
        s.spikerecorders.append(spikerecorder)
        s.pc.cell(gid, s.spikerecorders[s.cellsperhost])
        s.cellsperhost += 1 # contain cell numbers per host including PMd and P
    print('  Number of cells on node %i: %i ' % (s.rank,len(s.cells)))
    s.pc.barrier()


    ## Calculate motor command cell ranges so can be used for EDSC and IDSC connectivity
    nCells = s.motorCmdEndCell - s.motorCmdStartCell 
    s.motorCmdCellRange = []
    for i in range(s.nMuscles):
        s.motorCmdCellRange.append(range(s.motorCmdStartCell + (nCells/s.nMuscles)*i, s.motorCmdStartCell + (nCells/s.nMuscles)*i + (nCells/s.nMuscles) )) # cells used to for shoulder motor command
     

    ## Calculate distances and probabilities
    if s.rank==0: print('Calculating connection probabilities (est. time: %i s)...' % (s.performance*s.cellsperhost**2/3e4))
    conncalcstart = s.time() # See how long connecting the cells takes
    s.nconnpars = 5 # Connection parameters: pre- and post- cell ID, weight, distances, delays
    s.conndata = [[] for i in range(s.nconnpars)] # List for storing connections
    nPostCells = 0
    EDSCpre = [] # to keep track of EB5->EDSC connection and replicate in EB5->IDSC
    for c in range(s.cellsperhost): # Loop over all postsynaptic cells on this host (has to be postsynaptic because of gid_connect)
        gid = s.gidVec[c] # Increment global identifier       
        if s.cellnames[gid] == 'PMd' or s.cellnames[gid] == 'ASC':
            # There are no presynaptic connections for PMd or ASC.
            continue
        nPostCells += 1
        if s.toroidal: 
            xpath=(abs(s.xlocs-s.xlocs[gid]))**2
            xpath2=(s.modelsize-abs(s.xlocs-s.xlocs[gid]))**2
            xpath[xpath2<xpath]=xpath2[xpath2<xpath]
            ypath=(abs(s.ylocs-s.ylocs[gid]))**2
            ypath2=(s.modelsize-abs(s.ylocs-s.ylocs[gid]))**2
            ypath[ypath2<ypath]=ypath2[ypath2<ypath]
            zpath=(abs(s.zlocs-s.zlocs[gid]))**2
            distances = sqrt(xpath + ypath) # Calculate all pairwise distances
            distances3d = sqrt(xpath + ypath + zpath) # Calculate all pairwise 3d distances
        else: 
            distances = sqrt((s.xlocs-s.xlocs[gid])**2 + (s.ylocs-s.ylocs[gid])**2) # Calculate all pairwise distances
            distances3d = sqrt((s.xlocs-s.xlocs[gid])**2 + (s.ylocs-s.ylocs[gid])**2 + (s.zlocs-s.zlocs[gid])**2) # Calculate all pairwise distances
        allconnprobs = s.scaleconnprob[s.EorI,s.EorI[gid]] * s.connprobs[s.cellpops,s.cellpops[gid]] * exp(-distances/s.connfalloff[s.EorI]) # Calculate pairwise probabilities
        allconnprobs[gid] = 0 # Prohibit self-connections using the cell's GID
        seed(s.id32('%d'%(s.randseed+gid))) # Reset random number generator  
        allrands = rand(s.ncells) # Create an array of random numbers for checking each connection  
        if s.PMdinput == 'Plexon':
            for c in xrange(s.popGidStart[s.PMd], s.popGidEnd[s.PMd] + 1):
                allrands[c] = 1
            if s.cellnames[gid] == 'ER5': # PMd->ER5 conn (full conn)
                PMdId = (gid % s.server.numPMd) + s.ncells - s.server.numPMd #CHECK THIS!
                allconnprobs[PMdId] = s.connprobs[s.PMd,s.ER5] # to make this connected to ER5
                allrands[PMdId] = 0 # to make this connect to ER5
                distances[PMdId] = 300 # to make delay 5 in conndata[3] 
        makethisconnection = allconnprobs>allrands # Perform test to see whether or not this connection should be made
        preids = array(makethisconnection.nonzero()[0],dtype='int') # Return True elements of that array for presynaptic cell IDs
        if s.PMdinput == 'targetSplit' and s.cellnames[gid] == 'ER5': # PMds 0-47 -> ER5 0-47 ; PMds 48-95 -> ER5 48-95 
            if gid < s.popGidStart[s.ER5] + s.popnumbers[s.ER5]/2:
                prePMd = [(x - s.popGidStart[s.ER5])%(s.popnumbers[s.PMd]/2) + s.popGidStart[s.PMd] for x in range(gid, gid+1)] # input from 2 PMds  
            else:
                prePMd = [(x - s.popGidStart[s.ER5])%(s.popnumbers[s.PMd]/2) + s.popGidStart[s.PMd] + s.popnumbers[s.PMd]/2 for x in range(gid, gid+1)] # input from 2 PMds  
            if array(prePMd).all() < s.popGidEnd[s.PMd]: 
                #print 'prePMd=%d to ER5=%d:'%(prePMd[0],gid)
                preids = concatenate([preids, prePMd])
        if s.cellnames[gid] == 'EDSC': # save EDSC presyn cells to replicate in IDSC, and add inputs from IDSC
            EDSCpre.append(array(preids)) # save EDSC presyn cells before adding IDSC input
            invPops = [1, 0, 3, 2] # each postsyn ESDC cell will receive input from all the antagonistic muscle IDSCs
            IDSCpre = [s.motorCmdCellRange[invPops[i]] - s.popGidStart[s.EDSC] + s.popGidStart[s.IDSC] for i in range(s.nMuscles) if gid in s.motorCmdCellRange[i]][0]
            preids = concatenate([preids, IDSCpre]) # add IDSC presynaptic input to EDSC 
        elif s.cellnames[gid] == 'IDSC': # use same presyn cells as for EDSC (antagonistic inhibition)
            preids = array(EDSCpre.pop(0))
        postids = array(gid+zeros(len(preids)),dtype='int') # Post-synaptic cell IDs
        s.conndata[0].append(preids) # Append pre-cell ID
        s.conndata[1].append(postids) # Append post-cell ID
        s.conndata[2].append(distances[preids]) # Distances
        s.conndata[3].append(s.mindelay + distances3d[preids]/float(s.velocity)) # Calculate the delays
        wt1 = s.scaleconnweight[s.EorI[preids],s.EorI[postids]] # N weight scale factors -- WARNING, might be flipped
        wt2 = s.connweights[s.cellpops[preids],s.cellpops[postids],:] # NxM inter-population weights
        wt3 = s.receptorweight[:] # M receptor weights
        finalweights = transpose(wt1*transpose(wt2*wt3)) # Multiply out population weights with receptor weights to get NxM matrix
        s.conndata[4].append(finalweights) # Initialize weights to 0, otherwise get memory leaks
    for pp in range(s.nconnpars): s.conndata[pp] = array(concatenate([s.conndata[pp][c] for c in range(nPostCells)])) # Turn pre- and post- cell IDs lists into vectors
    s.nconnections = len(s.conndata[0]) # Find out how many connections we're going to make
    conncalctime = time()-conncalcstart # See how long it took
    if s.rank==0: print('  Done; time = %0.1f s' % conncalctime)


    # set plastic connections based on plasConnsType (from evol alg)
    if s.plastConnsType == 0:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC]] # only spinal cord 
    elif s.plastConnsType == 1:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.ER2,s.ER5], [s.ER5,s.EB5], [s.ER2,s.EB5], [s.ER5,s.ER2]] # + L2-L5
    elif s.plastConnsType == 2:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.ER2,s.ER5], [s.ER5,s.EB5], [s.ER2,s.EB5], [s.ER5,s.ER2],\
        [s.ER5,s.ER6], [s.ER6,s.ER5], [s.ER6,s.EB5]] # + L6
    elif s.plastConnsType == 3:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.ER2,s.ER5], [s.ER5,s.EB5], [s.ER2,s.EB5], [s.ER5,s.ER2],\
         [s.ER5,s.ER6], [s.ER6,s.ER5], [s.ER6,s.EB5], \
         [s.ER2,s.IL2], [s.ER2,s.IF2], [s.ER5,s.IL5], [s.ER5,s.IF5], [s.EB5,s.IL5], [s.EB5,s.IF5]] # + Inh
    # same with additional plasticity between PMd->L5A
    elif s.plastConnsType == 4: 
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.PMd,s.ER5]] # only spinal cord + pmd
    elif s.plastConnsType == 5:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.PMd,s.ER5], # spinal cord + pmd
         [s.ER2,s.ER5], [s.ER5,s.EB5], [s.ER2,s.EB5], [s.ER5,s.ER2]] # + L2-L5
    elif s.plastConnsType == 6:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.PMd,s.ER5], # spinal cord + pmd
        [s.ER2,s.ER5], [s.ER5,s.EB5], [s.ER2,s.EB5], [s.ER5,s.ER2], # + L2-L5
        [s.ER5,s.ER6], [s.ER6,s.ER5], [s.ER6,s.EB5]] # + L6
    elif s.plastConnsType == 7:
        s.plastConns = [[s.ASC,s.ER2], [s.EB5,s.EDSC], [s.EB5,s.IDSC], [s.PMd,s.ER5], # spinal cord + pmd 
        [s.ER2,s.ER5], [s.ER5,s.EB5], [s.ER2,s.EB5], [s.ER5,s.ER2], # + L2-L5
        [s.ER5,s.ER6], [s.ER6,s.ER5], [s.ER6,s.EB5], # + L6
        [s.ER2,s.IL2], [s.ER2,s.IF2], [s.ER5,s.IL5], [s.ER5,s.IF5], [s.EB5,s.IL5], [s.EB5,s.IF5]]  # + Inh



    ## Actually make connections
    if s.rank==0: print('Making connections (est. time: %i s)...' % (s.performance*s.nconnections/9e2))
    print('  Number of connections on host %i: %i' % (s.rank, s.nconnections))
    connstart = time() # See how long connecting the cells takes
    s.connlist = [] # Create array for storing each of the connections
    s.stdpconndata = [] # Store data on STDP connections
    if s.usestdp: # STDP enabled?
        s.stdpmechs = [] # Initialize array for STDP mechanisms
        s.precons = [] # Initialize array for presynaptic spike counters
        s.pstcons = [] # Initialize array for postsynaptic spike counters
    for con in range(s.nconnections): # Loop over each connection
        pregid = s.conndata[0][con] # GID of presynaptic cell    
        pstgid = s.conndata[1][con] # Index of postsynaptic cell
        pstid = s.gidDic[pstgid]# Index of postynaptic cell -- convert from GID to local
        newcon = s.pc.gid_connect(pregid, s.cells[pstid]) # Create a connection
        newcon.delay = s.conndata[3][con] # Set delay
        for r in range(s.nreceptors): newcon.weight[r] = s.conndata[4][con][r] # Set weight of connection
        s.connlist.append(newcon) # Connect the two cells
        if s.usestdp and ([s.cellpops[pregid],s.cellpops[pstgid]] in s.plastConns): # If using STDP and these pops are set to be plastic connections
            if sum(abs(s.stdprates[s.EorI[pregid],:]))>0 or sum(abs(s.RLrates[s.EorI[pregid],:]))>0: # Don't create an STDP connection if the learning rates are zero
                for r in range(s.nreceptors): # Need a different STDP instances for each receptor
                    if newcon.weight[r]>0: # Only make them for nonzero connections
                        stdpmech = h.STDP(0,sec=s.dummies[pstid]) # Create STDP adjuster
                        stdpmech.hebbwt = s.stdprates[s.EorI[pregid],0] # Potentiation rate
                        stdpmech.antiwt = s.stdprates[s.EorI[pregid],1] # Depression rate
                        stdpmech.wmax = s.maxweight # Maximum synaptic weight
                        precon = s.pc.gid_connect(pregid,stdpmech); precon.weight[0] = 1 # Send presynaptic spikes to the STDP adjuster
                        pstcon = s.pc.gid_connect(pstgid,stdpmech); pstcon.weight[0] = -1 # Send postsynaptic spikes to the STDP adjuster
                        h.setpointer(s.connlist[-1]._ref_weight[r],'synweight',stdpmech) # Associate the STDP adjuster with this weight
                        s.stdpmechs.append(stdpmech) # Save STDP adjuster
                        s.precons.append(precon) # Save presynaptic spike source
                        s.pstcons.append(pstcon) # Save postsynaptic spike source
                        s.stdpconndata.append([pregid,pstgid,r]) # Store presynaptic cell ID, postsynaptic, and receptor
                        if s.verbose: stdpmech.verbose = 1
                        if s.useRL: # using RL
                            stdpmech.RLon = 1 # make sure RL is on
                            stdpmech.RLhebbwt = s.RLrates[s.EorI[pregid],0] # Potentiation rate
                            stdpmech.RLantiwt = s.RLrates[s.EorI[pregid],1] # Depression rate
                            stdpmech.tauhebb = stdpmech.tauanti = s.stdpwin # stdp time constant(ms)
                            stdpmech.RLwindhebb = stdpmech.RLwindhebb = s.eligwin # RL eligibility trace window length (ms)
                            stdpmech.useRLexp = s.useRLexp # RL 
                            stdpmech.softthresh = s.useRLsoft # RL soft-thresholding
                        else:
                            stdpmech.RLon = 0 # make sure RL is off
                 
    s.nstdpconns = len(s.stdpconndata) # Get number of STDP connections
    conntime = time()-connstart # See how long it took
    if s.usestdp: print('  Number of STDP connections on host %i: %i' % (s.rank, s.nstdpconns))
    if s.rank==0: print('  Done; time = %0.1f s' % conntime)


###############################################################################
### Add stimulation
###############################################################################

def addStimulation():
    if s.usestims:
        s.stimstruct = [] # For saving
        s.stimrands=[] # Create input connections
        s.stimsources=[] # Create empty list for storing synapses
        s.stimconns=[] # Create input connections
        s.stimtimevecs = [] # Create array for storing time vectors
        s.stimweightvecs = [] # Create array for holding weight vectors
        if s.saveraw: 
            s.stimspikevecs=[] # A list for storing actual cell voltages (WARNING, slow!)
            s.stimrecorders=[] # And for recording spikes
        for stim in range(len(s.stimpars)): # Loop over each stimulus type
            ts = s.stimpars[stim] # Stands for "this stimulus"
            ts.loc = ts.loc * s.modelsize # scale cell locations to model size
            stimvecs = s.makestim(ts.isi, ts.var, ts.width, ts.weight, ts.sta, ts.fin, ts.shape) # Time-probability vectors
            s.stimstruct.append([ts.name, stimvecs]) # Store for saving later
            s.stimtimevecs.append(h.Vector().from_python(stimvecs[0]))
            
            for c in range(s.cellsperhost):
                gid = s.cellsperhost*int(s.rank)+c # For deciding E or I    
                seed(s.id32('%d'%(s.randseed+gid))) # Reset random number generator for this cell
                if ts.fraction>rand(): # Don't do it for every cell necessarily
                    if any(s.cellpops[gid]==ts.pops) and s.xlocs[gid]>=ts.loc[0,0] and s.xlocs[gid]<=ts.loc[0,1] and s.ylocs[gid]>=ts.loc[1,0] and s.ylocs[gid]<=ts.loc[1,1]:
                        
                        maxweightincrease = 20 # Otherwise could get infinitely high, infinitely close to the stimulus
                        distancefromstimulus = sqrt(sum((array([s.xlocs[gid], s.ylocs[gid]])-s.modelsize*ts.falloff[0])**2))
                        fallofffactor = min(maxweightincrease,(ts.falloff[1]/distancefromstimulus)**2)
                        s.stimweightvecs.append(h.Vector().from_python(stimvecs[1]*fallofffactor)) # Scale by the fall-off factor
                        
                        stimrand = h.Random()
                        stimrand.MCellRan4() # If everything has the same seed, should happen at the same time
                        stimrand.negexp(1)
                        stimrand.seq(s.id32('%d'%(s.randseed+gid))*1e3) # Set the sequence i.e. seed
                        s.stimrands.append(stimrand)
                        
                        stimsource = h.NetStim() # Create a NetStim
                        stimsource.interval = ts.rate**-1*1e3 # Interval between spikes
                        stimsource.number = 1e9 # Number of spikes
                        stimsource.noise = ts.noise # Fractional noise in timing
                        stimsource.noiseFromRandom(stimrand) # Set it to use this random number generator
                        s.stimsources.append(stimsource) # Save this NetStim
                        
                        stimconn = h.NetCon(stimsource, s.cells[c]) # Connect this noisy input to a cell
                        for r in range(s.nreceptors): stimconn.weight[r]=0 # Initialize weights to 0, otherwise get memory leaks
                        s.stimweightvecs[-1].play(stimconn._ref_weight[0], s.stimtimevecs[-1]) # Play most-recently-added vectors into weight
                        stimconn.delay=s.mindelay # Specify the delay in ms -- shouldn't make a spot of difference
                        s.stimconns.append(stimconn) # Save this connnection
        
                        if s.saveraw: # and c <=100:
                            stimspikevec = h.Vector() # Initialize vector
                            s.stimspikevecs.append(stimspikevec) # Keep all those vectors
                            stimrecorder = h.NetCon(stimsource, None)
                            stimrecorder.record(stimspikevec) # Record simulation time
                            s.stimrecorders.append(stimrecorder)
        print('  Number of stimuli created on host %i: %i' % (s.rank, len(s.stimsources)))


###############################################################################
### Add background inputs
###############################################################################
def addBackground():
    if s.rank==0: print('Creating background inputs...')
    s.backgroundsources=[] # Create empty list for storing synapses
    s.backgroundrands=[] # Create random number generators
    s.backgroundconns=[] # Create input connections
    s.backgroundgid=[] # Target cell gid for each input
    if s.savebackground:
        s.backgroundspikevecs=[] # A list for storing actual cell voltages (WARNING, slow!)
        s.backgroundrecorders=[] # And for recording spikes
    for c in range(s.cellsperhost): 
        gid = s.gidVec[c]
        if s.cellnames[gid] == 'ASC' or s.cellnames[gid] == 'PMd' : # These pops won't receive background stimulations.
            pass
        else:
            backgroundrand = h.Random()
            backgroundrand.MCellRan4(gid,gid*2)
            backgroundrand.negexp(1)
            s.backgroundrands.append(backgroundrand)
            if s.cellnames[gid] == 'EDSC' or s.cellnames[gid] == 'IDSC':
                backgroundsource = h.NSLOC() # Create a NSLOC  
                backgroundsource.interval = s.backgroundrateMin**-1*1e3 # Take inverse of the frequency and then convert from Hz^-1 to ms
                backgroundsource.noise = 0.3 # Fractional noise in timing
            elif s.cellnames[gid] == 'EB5':
                backgroundsource = h.NSLOC() # Create a NSLOC  
                backgroundsource.interval = s.backgroundrate**-1*1e3 # Take inverse of the frequency and then convert from Hz^-1 to ms
                backgroundsource.noise = s.backgroundnoise # Fractional noise in timing
            else:
                backgroundsource = h.NetStim() # Create a NetStim
                backgroundsource.interval = s.backgroundrate**-1*1e3 # Take inverse of the frequency and then convert from Hz^-1 to ms
                backgroundsource.noiseFromRandom(backgroundrand) # Set it to use this random number generator
                backgroundsource.noise = s.backgroundnoise # Fractional noise in timing

            backgroundsource.number = s.backgroundnumber # Number of spikes
            s.backgroundsources.append(backgroundsource) # Save this NetStim
            s.backgroundgid.append(gid) # append cell gid associated to this netstim
            
            backgroundconn = h.NetCon(backgroundsource, s.cells[c]) # Connect this noisy input to a cell
            for r in range(s.nreceptors): backgroundconn.weight[r]=0 # Initialize weights to 0, otherwise get memory leaks
            if s.cellnames[gid] == 'EDSC' or s.cellnames[gid] == 'IDSC':
                backgroundconn.weight[s.backgroundreceptor] = s.backgroundweightExplor # Specify the weight for the EDSC, IDSC and PMd background input
            elif s.cellnames[gid] == 'EB5' and s.explorMovs == 2: 
                backgroundconn.weight[s.backgroundreceptor] = s.backgroundweightExplor # Weight for EB5 input if explor movs via EB5 
            else:
                backgroundconn.weight[s.backgroundreceptor] = s.backgroundweight[s.EorI[gid]] # Specify the weight -- 1 is NMDA receptor for smoother, more summative activation
            backgroundconn.delay=2 # Specify the delay in ms -- shouldn't make a spot of difference
            s.backgroundconns.append(backgroundconn) # Save this connnection
        
            if s.savebackground:
                backgroundspikevec = h.Vector() # Initialize vector
                s.backgroundspikevecs.append(backgroundspikevec) # Keep all those vectors
                backgroundrecorder = h.NetCon(backgroundsource, None)
                backgroundrecorder.record(backgroundspikevec) # Record simulation time
                s.backgroundrecorders.append(backgroundrecorder)
    print('  Number created on host %i: %i' % (s.rank, len(s.backgroundsources)))
    s.pc.barrier()


###############################################################################
### Setup Simulation
###############################################################################
def setupSim():
    ## reset time variables
    s.timeoflastRL = -inf # Never RL
    s.timeoflastsave = -inf # Never saved
    s.timeoflastexplor = -inf # time when last exploratory movement was updated

    # Initialize STDP -- just for recording
    if s.usestdp:
        s.weightchanges = []
        if s.rank==0: print('\nSetting up STDP...')
        if s.usestdp:
            s.weightchanges = [[] for ps in range(s.nstdpconns)] # Create an empty list for each STDP connection -- warning, slow with large numbers of connections!
        for ps in range(s.nstdpconns): s.weightchanges[ps].append([0, s.stdpmechs[ps].synweight]) # Time of save (0=initial) and the weight


    ## Set up LFP recording
    s.lfptime = [] # List of times that the LFP was recorded at
    s.nlfps = len(s.lfppops) # Number of distinct LFPs to calculate
    s.hostlfps = [] # Voltages for calculating LFP
    s.lfpcellids = [[] for pop in range(s.nlfps)] # Create list of lists of cell IDs
    for c in range(s.cellsperhost): # Loop over each cell and decide which LFP population, if any, it belongs to
        gid = s.gidVec[c] # Get this cell's GID
        if s.cellnames[gid] == 'ASC' or s.cellnames[gid] == 'PMd': # 'ER2' won't be fired by background stimulations.
                continue 
        for pop in range(s.nlfps): # Loop over each LFP population
            thispop = s.cellpops[gid] # Population of this cell
            if sum(s.lfppops[pop]==thispop)>0: # There's a match
                s.lfpcellids[pop].append(gid) # Flag this cell as belonging to this LFP population


    ## Set up raw recording
    s.rawrecordings = [] # A list for storing actual cell voltages (WARNING, slow!)
    if s.saveraw: 
        if s.rank==0: print('\nSetting up raw recording...')
        s.nquantities = 5 # Number of variables from each cell to record from
        # Later this part should be modified because NSLOC doesn't have V, u and I.
        for c in range(s.cellsperhost):
            gid = s.gidVec[c] # Get this cell's GID
            if s.cellnames[gid] == 'ASC' or s.cellnames[gid] == 'PMd': # NSLOC doesn't have V, u and I
                continue 
            recvecs = [h.Vector() for q in range(s.nquantities)] # Initialize vectors
            recvecs[0].record(h._ref_t) # Record simulation time
            recvecs[1].record(s.cells[c]._ref_V) # Record cell voltage
            recvecs[2].record(s.cells[c]._ref_u) # Record cell recovery variable
            recvecs[3].record(s.cells[c]._ref_I) # Record cell current
            recvecs[4].record(s.cells[c]._ref_gAMPA)
            # recvecs[5].record(s.cells[c]._ref_gNMDA)
            # recvecs[6].record(s.cells[c]._ref_gGABAA)
            # recvecs[7].record(s.cells[c]._ref_gGABAB)
            # recvecs[8].record(s.cells[c]._ref_gOpsin)
            s.rawrecordings.append(recvecs) # Keep all those vectors


    ## Set up virtual arm
    if s.useArm != 'None':
        if s.rank==0: print('\nSetting up virtual arm...')
        s.arm = Arm(s.useArm, s.animArm, s.graphsArm) 
        s.arm.targetid = s.targetid
        s.arm.setup(s)#duration, loopstep, RLinterval, pc, scale, popnumbers, p)


    ## Communication setup for plexon input
    if s.PMdinput == 'Plexon':
        h('''
            objref cvode
            cvode = new CVode()
            tstop = 0
        ''')

        if s.isOriginal == 0: # With communication program
            if s.rank == 0: 
                #serverManager = s.server.Manager() # isDp in confis.py = 0
                s.server.Manager.start() # launch sever process
                print "Server process completed and callback function initalized"
            e = s.server.Manager.Event() # Queue callback function in the NEURON queue

        
        # Wait for external spikes for PMd from Plexon  
            if s.rank == 0:
                if s.server.isCommunication == 1:
                    s.server.getServerInfo() # show parameters of the server process
                    print "[Waiting for spikes; run the client on Windows machine...]"
                    while s.server.queue.empty(): # only Rank 0 is waiting for spikes in the queue.
                        pass
            s.pc.barrier() # other workers are waiting here.

    ## Play back raw spikes from recorded PMd neurons, into model PMd population
    elif s.PMdinput == 'spikes':
        # if s.rank == 0:
        rawSpikesPMd = loadmat(s.spikesPMdFile)['pmdData'] # load raw data
        numrawcells = len(rawSpikesPMd[0][0])

        # implement lesion
        if s.PMdlesion > 0:
            numLesionedCells = int(round(s.PMdlesion*numrawcells))
            if s.rank==0: print "Lesioning PMd input... removed spike times of %d (%d%%) cells"%(numLesionedCells, s.PMdlesion*100)
            for itarget in range(len(rawSpikesPMd)):
                for itrial in range(len(rawSpikesPMd[0])):
                    for icell in range(numLesionedCells):
                        rawSpikesPMd[itarget][itrial][numrawcells-1-icell]['spkt'] = [array([])]  # remove spike times of lesion % of cells

        # generate spike vectors based on training time, trial duration, and target presentation (eg. alternating trials)
        if s.duration == 1e3: # if sim duration=1sec, assume its the test trial and select PMd spikes based on targetid
            spktPMd = [rawSpikesPMd[s.targetid][s.repeatSingleTrials[s.targetid]][icell]['spkt'][0] for icell in range(numrawcells)] 
        elif s.repeatSingleTrials[0] > -1: # use single trials for each target during training
            spktPMd = []
            for icell in range(numrawcells):
                spkt = []
                [spkt.extend(list(rawSpikesPMd[itarget][s.repeatSingleTrials[itarget]][icell]['spkt'][0] + (1000*itrial))) \
                    for itrial,itarget in enumerate(s.trialTargets[:-1])] # replicate spike times over trials
                spktPMd.append(spkt) 
        else: # use all available trials for each target during training
            pass
        # play back PMd spikes using VecStims
        s.tvecPMdlist = []
        gids = [i for i in s.gidVec if i in range(s.popGidStart[s.PMd], s.popGidEnd[s.PMd])] # calcualate gids in this node
        for icell in gids: # for each unique cell/vecstim
            spkcell = spktPMd[icell%numrawcells]
            tvecPMd = h.Vector().from_python(spkcell) # find spikes for that vecstim
            s.tvecPMdlist.append(tvecPMd)  # store vector to avoid runtime error
            s.cells[s.gidDic[icell]].play(tvecPMd)  # play back sequence of spikes


###############################################################################
### Run Simulation
###############################################################################
def runSim():
    if s.rank == 0:
        print('\nRunning...')
        runstart = time() # See how long the run takes

    # set cache_efficient on
    h('objref cvode')
    h('cvode = new CVode()')
    h.cvode.cache_efficient(1)

    s.pc.set_maxstep(10) # MPI: Set the maximum integration time in ms -- not very important
    init() # Initialize the simulation

    while round(h.t) < s.duration:
        run(min(s.duration,h.t+s.loopstep)) # MPI: Get ready to run the simulation (it isn't actually run until pc.runworker() is called I think)
        if s.server.simMode == 0:
            if s.rank==0 and (round(h.t) % s.progupdate)==0: print('  t = %0.1f s (%i%%; time consumed: %0.1f s)' % (h.t/1e3, int(h.t/s.duration*100), (time()-runstart)))
        else:
            if s.rank==0: print('  t = %0.1f s (%i%%; time consumed: %0.1f s)' % (h.t/1e3, int(h.t/s.duration*100), (time()-runstart)))

        # Calculate LFP -- WARNING, need to think about how to optimize
        if s.savelfps:
            s.lfptime.append(h.t) # Append current time
            tmplfps = zeros((s.nlfps)) # Create empty array for storing LFP voltages
            for pop in range(s.nlfps):
                for c in range(len(s.lfpcellids[pop])):
                    id = s.gidDic[s.lfpcellids[pop][c]]# Index of postynaptic cell -- convert from GID to local
                    tmplfps[pop] += s.cells[id].V # Add voltage to LFP estimate
                if s.verbose:
                    if s.server.Manager.ns.isnan(tmplfps[pop]) or s.server.Manager.ns.isinf(tmplfps[pop]):
                        print "Nan or inf"
            s.hostlfps.append(tmplfps) # Add voltages

        # Periodic weight saves
        if s.usestdp: 
            timesincelastsave = h.t - s.timeoflastsave
            if timesincelastsave >= s.timebetweensaves:
                s.timeoflastsave = h.t
                #if s.rank == 0: print 'Recording weight changes at time ', h.t
                for ps in range(s.nstdpconns):
                    if s.stdpmechs[ps].synweight != s.weightchanges[ps][-1][-1]: # Only store connections that changed; [ps] = this connection; [-1] = last entry; [-1] = weight
                        s.weightchanges[ps].append([s.timeoflastsave, s.stdpmechs[ps].synweight])
                       
        ## Virtual arm 
        if s.useArm != 'None':
            armStart = time()
            s.arm.run(h.t, s) # run virtual arm apparatus (calculate command, move arm, feedback)
            if s.useRL and (h.t - s.timeoflastRL >= s.RLinterval): # if time for next RL
                s.timeoflastRL = h.t
                vec = h.Vector()
                if s.rank == 0:
                    critic = s.arm.RLcritic(h.t) # get critic signal (-1, 0 or 1)
                    s.pc.broadcast(vec.from_python([critic]), 0) # convert python list to hoc vector for broadcast data received from arm
                    #print critic
                else: # other workers
                    s.pc.broadcast(vec, 0)
                    critic = vec.to_python()[0]
                if critic != 0: # if critic signal indicates punishment (-1) or reward (+1)
                    for stdp in s.stdpmechs: # for all connections in stdp conn list
                        #print 'stdp_before: ', stdp.synweight
                        stdp.reward_punish(float(critic)) # run stds.mod method to update syn weights based on RL
                        #print stdp.tlastpre
                        #print stdp.tlastpost
                        #stdp.adjustweight(float(0.5))
                        #sleep(0.001)
                        #print 'stdp_after: ', stdp.synweight
            # Synaptic scaling?
        
            #print(' Arm time = %0.4f s') % (time() - armStart)

        ## Time adjustment for online mode simulation
        if s.PMdinput == 'Plexon' and s.server.simMode == 1:                   
            # To avoid izhi cell's over shooting when h.t moves forward because sim is slow.
            for c in range(s.cellsperhost): 
                gid = s.gidVec[c]
                if s.cellnames[gid] == 'PMd': # 'PMds don't have t0 variable.
                    continue
                s.cells[c].t0 = s.server.newCurrTime.value - h.dt             
            dtSave = h.dt # save original dt
            h.dt = s.server.newCurrTime.value - h.t # new dt
            active = h.cvode.active()
            if active != 0:
                h.cvode.active(0)         
            h.fadvance() # Integrate with new dt
            if active != 0:
                h.cvode.active(1)         
            h.dt = dtSave # Restore orignal dt   
                
    if s.rank==0: 
        s.runtime = time()-runstart # See how long it took
        print('  Done; run time = %0.1f s; real-time ratio: %0.2f.' % (s.runtime, s.duration/1000/s.runtime))
    s.pc.barrier() # Wait for all hosts to get to this point


###############################################################################
### Finalize Simulation  (gather data from nodes, etc.)
###############################################################################
def finalizeSim():
        
    ## Variables to unpack data from all hosts

    ## Pack data from all hosts
    if s.rank==0: print('\nGathering spikes...')
    gatherstart = time() # See how long it takes to plot
    for host in range(s.nhosts): # Loop over hosts
        if host==s.rank: # Only act on a single host
            hostspikecells=array([])
            hostspiketimes=array([])
            for c in range(len(s.hostspikevecs)): # fails when saving raw
                thesespikes = array(s.hostspikevecs[c]) # Convert spike times to an array
                nthesespikes = len(thesespikes) # Find out how many of spikes there were for this cell
                hostspiketimes = concatenate((hostspiketimes, thesespikes)) # Add spikes from this cell to the list
                #hostspikecells = concatenate((hostspikecells, (c+host*s.cellsperhost)*ones(nthesespikes))) # Add this cell's ID to the list
                hostspikecells = concatenate((hostspikecells, s.gidVec[c]*ones(nthesespikes))) # Add this cell's ID to the list
            if s.saveraw:
                for c in range(len(s.rawrecordings)):
                    for q in range(len(s.rawrecordings[c])):
                        s.rawrecordings[c][q] = array(s.rawrecordings[c][q])
            messageid=s.pc.pack([hostspiketimes, hostspikecells, s.hostlfps, s.conndata, s.stdpconndata, s.weightchanges, s.rawrecordings]) # Create a mesage ID and store this value
            s.pc.post(host,messageid) # Post this message


    ## Unpack data from all hosts
    if s.rank==0: # Only act on a single host
        s.allspikecells = array([])
        s.allspiketimes = array([])
        s.lfps = zeros((len(s.lfptime),s.nlfps)) # Create an empty array for appending LFP data; first entry is for time
        s.allconnections = [array([]) for i in range(s.nconnpars)] # Store all connections
        s.allconnections[s.nconnpars-1] = zeros((0,s.nreceptors)) # Create an empty array for appending connections
        s.allstdpconndata = zeros((0,3)) # Create an empty array for appending STDP connection data
        if s.usestdp: s.allweightchanges = [] # empty list so weightchanges in this node don't appear twice
        s.totalspikes = 0 # Keep a running tally of the number of spikes
        s.totalconnections = 0 # Total number of connections
        s.totalstdpconns = 0 # Total number of stdp connections
        if s.saveraw: s.allraw = []        
        for host in range(s.nhosts): # Loop over hosts
            s.pc.take(host) # Get the last message
            hostdata = s.pc.upkpyobj() # Unpack them
            s.allspiketimes = concatenate((s.allspiketimes, hostdata[0])) # Add spikes from this cell to the list
            s.allspikecells = concatenate((s.allspikecells, hostdata[1])) # Add this cell's ID to the list
            if s.savelfps: s.lfps += array(hostdata[2]) # Sum LFP voltages
            for pp in range(s.nconnpars): s.allconnections[pp] = concatenate((s.allconnections[pp], hostdata[3][pp])) # Append pre/post synapses
            if s.usestdp and len(hostdata[4]): # Using STDP and at least one STDP connection
                s.allstdpconndata = concatenate((s.allstdpconndata, hostdata[4])) # Add data on STDP connections
                for ps in range(len(hostdata[4])): s.allweightchanges.append(hostdata[5][ps]) # "ps" stands for "plastic synapse"
            if s.saveraw:
                for c in range(len(hostdata[6])): s.allraw.append(hostdata[6][c]) # Append cell-by-cell

        s.totalspikes = len(s.allspiketimes) # Keep a running tally of the number of spikes
        s.totalconnections = len(s.allconnections[0]) # Total number of connections
        s.totalstdpconns = len(s.allstdpconndata) # Total number of STDP connections
        

    # Record background spike data (cliff: only for one node since takes too long to pack for all and just needed for debugging)
    if s.savebackground and s.usebackground:
        s.allbackgroundspikecells=array([])
        s.allbackgroundspiketimes=array([])
        for c in range(len(s.backgroundspikevecs)):
            thesespikes = array(s.backgroundspikevecs[c])
            s.allbackgroundspiketimes = concatenate((s.allbackgroundspiketimes, thesespikes)) # Add spikes from this stimulator to the list
            s.allbackgroundspikecells = concatenate((s.allbackgroundspikecells, c+zeros(len(thesespikes)))) # Add this cell's ID to the list
        s.backgrounddata = transpose(vstack([s.allbackgroundspikecells,s.allbackgroundspiketimes]))
    else: s.backgrounddata = [] # For saving s no error
    
    if s.saveraw and s.usestims:
        s.allstimspikecells=array([])
        s.allstimspiketimes=array([])
        for c in range(len(s.stimspikevecs)):
            thesespikes = array(s.stimspikevecs[c])
            s.allstimspiketimes = concatenate((s.allstimspiketimes, thesespikes)) # Add spikes from this stimulator to the list
            s.allstimspikecells = concatenate((s.allstimspikecells, c+zeros(len(thesespikes)))) # Add this cell's ID to the list
        s.stimspikedata = transpose(vstack([s.allstimspikecells,s.allstimspiketimes]))
    else: s.stimspikedata = [] # For saving so no error

    gathertime = time()-gatherstart # See how long it took
    if s.rank==0: print('  Done; gather time = %0.1f s.' % gathertime)
    s.pc.barrier()

    #mindelay = s.pc.allreduce(s.pc.set_maxstep(10), 2) # flag 2 returns minimum value
    #if s.rank==0: print 'Minimum delay (time-step for queue exchange) is ',mindelay


    ## Finalize virtual arm (es. close pipes, saved data)
    if s.useArm != 'None':
        s.arm.close(s)


    # terminate the server process
    if s.PMdinput == 'Plexon':
        if s.isOriginal == 0:
            s.server.Manager.stop()


    ## Print statistics
    if s.rank == 0:
        print('\nAnalyzing...')
        s.firingrate = float(s.totalspikes)/s.ncells/s.duration*1e3 # Calculate firing rate -- confusing but cool Python trick for iterating over a list
        s.connspercell = s.totalconnections/float(s.ncells) # Calculate the number of connections per cell
        print('  Run time: %0.1f s (%i-s sim; %i scale; %i cells; %i workers)' % (s.runtime, s.duration/1e3, s.scale, s.ncells, s.nhosts))
        print('  Spikes: %i (%0.2f Hz)' % (s.totalspikes, s.firingrate))
        print('  Connections: %i (%i STDP; %0.2f per cell)' % (s.totalconnections, s.totalstdpconns, s.connspercell))
        print('  Mean connection distance: %0.2f um' % mean(s.allconnections[2]))
        print('  Mean connection delay: %0.2f ms' % mean(s.allconnections[3]))


###############################################################################
### Save data
###############################################################################
def saveData():
    if s.rank == 0:
        ## Save to txt file (spikes and conn)
        if s.savetxt: 
            filename = '../data/m1ms-spk.txt'
            fd = open(filename, "w")
            for c in range(len(s.allspiketimes)):
                print >> fd, int(s.allspikecells[c]), s.allspiketimes[c], s.popNamesDic[s.cellnames[int(s.allspikecells[c])]]
            fd.close()
            print "[Spikes are stored in", filename, "]"

            if s.verbose:
                filename = 'm1ms-conn.txt'
                fd = open(filename, "w")
                for c in range(len(s.allconnections[0])):
                    print >> fd, int(s.allconnections[0][c]), int(s.allconnections[1][c]), s.allconnections[2][c], s.allconnections[3][c], s.allconnections[4][c] 
                fd.close()
                print "[Connections are stored in", filename, "]"

        ## Save to mat file
        if s.savemat:
            savestart = time() # See how long it takes to save
            
            # Save simulation code
            filestosave = [] #'main.py', 'shared.py', 'network.py', 'arm.py', 'arminterface.py', 'server.py', 'izhi.py', 'izhi2007.mod', 'stdp.mod', 'nsloc.py', 'nsloc.mod'] # Files to save
            argv = [];
            simcode = [argv, filestosave] # Start off with input parameters, if any, and then the list of files being saved
            for f in range(len(filestosave)): # Loop over each file
                fobj = open(filestosave[f]) # Open it for reading
                simcode.append(fobj.readlines()) # Append to list of code to save
                fobj.close() # Close file object
            
            # Tidy variables
            spikedata = vstack([s.allspikecells,s.allspiketimes]).T # Put spike data together
            connections = vstack([s.allconnections[0],s.allconnections[1]]).T # Put connection data together
            distances = s.allconnections[2] # Pull out distances
            delays = s.allconnections[3] # Pull out delays
            weights = s.allconnections[4] # Pull out weights
            stdpdata = s.allstdpconndata # STDP connection data
            if s.usestims: stimdata = [vstack(s.stimstruct[c][1]).T for c in range(len(stimstruct))] # Only pull out vectors, not text, in stimdata

            # Save variables
            info = {'timestamp':datetime.today().strftime("%d %b %Y %H:%M:%S"), 'runtime':s.runtime, 'popnames':s.popnames, 'popEorI':s.popEorI} # Save date, runtime, and input arguments
            
            targetPos = s.arm.targetPos
            handPosAll = s.arm.handPosAll
            angAll = s.arm.angAll
            motorCmdAll = s.arm.motorCmdAll 
            targetidAll = s.arm.targetidAll 
            errorAll = s.arm.errorAll 
            criticAll = s.arm.criticAll
            if not hasattr(s, 'phase'): s.phase = ''
            s.filename = s.outfilestem+'_target_'+str(s.arm.targetid)+s.phase
            if s.armMinimalSave: # save only data related to arm reaching (for evol alg)
                variablestosave = ['targetPos', 'angAll', 'motorCmdAll', 'errorAll']
            else:
                variablestosave = ['info', 'targetPos', 'angAll', 'motorCmdAll', 'errorAll', 'simcode', 'spikedata', 's.cellpops', 's.cellnames', 's.cellclasses', 's.xlocs', 's.ylocs', 's.zlocs', 'connections', 'distances', 'delays', 'weights', 's.EorI']
            
            if s.savelfps:  
                variablestosave.extend(['s.lfptime', 's.lfps'])   
            if s.usestdp: 
                variablestosave.extend(['stdpdata', 's.allweightchanges'])
            if s.savebackground:
                variablestosave.extend(['s.backgrounddata'])
            if s.saveraw: 
                variablestosave.extend(['s.stimspikedata', 's.allraw'])
            if s.usestims: variablestosave.extend(['stimdata'])
            savecommand = "savemat(s.filename, {"
            for var in range(len(variablestosave)): savecommand += "'" + variablestosave[var].replace('s.','') + "':" + variablestosave[var] + ", " # Create command out of all the variables
            savecommand = savecommand[:-2] + "}, oned_as='column')" # Omit final comma-space and complete command
            
            print('Saving output as %s...' % s.filename)
            exec(savecommand) # Actually perform the save

            savetime = time()-savestart # See how long it took to save
            print('  Done; time = %0.1f s' % savetime)


###############################################################################
### Plot data
###############################################################################
def plotData():
    ## Plotting
    if s.rank == 0:
        if s.plotraster: # Whether or not to plot
            if (s.totalspikes>s.maxspikestoplot): 
                disp('  Too many spikes (%i vs. %i)' % (s.totalspikes, s.maxspikestoplot)) # Plot raster, but only if not too many spikes
            elif s.nhosts>1: 
                disp('  Plotting raster despite using too many cores (%i)' % s.nhosts) 
                analysis.plotraster()#;allspiketimes, allspikecells, EorI, ncells, connspercell, backgroundweight, firingrate, duration)
            else: 
                print('Plotting raster...')
                analysis.plotraster()#allspiketimes, allspikecells, EorI, ncells, connspercell, backgroundweight, firingrate, duration)

        if s.plotpeth:
            print('Plotting PETH...')
            analysis.plotPETH()

        if s.plotconn:
            print('Plotting connectivity matrix...')
            analysis.plotconn()

        if s.plotpsd:
            print('Plotting power spectral density')
            analysis.plotpsd()

        if s.plotweightchanges:
            print('Plotting weight changes...')
            analysis.plotweightchanges()
            #analysis.plotmotorpopchanges()

        if s.plot3darch:
            print('Plotting 3d architecture...')
            analysis.plot3darch()

        show(block=False)



