"""
MSARM

Code to connect a virtual arm to the M1 model
Multipe arm options depending on self.type:
- 'randomInput': the object provides random values matching the format (used for test/debugging)
- 'dummyArm': simple kinematic arm implemented in python 
- 'musculoskeletal': realistic musculoskeletal arm implemented in C++ and interfaced via pipes

Adapted from arm.hoc in arm2dms


Version: 2015jan28 by salvadordura@gmail.com
"""

from neuron import h
import arminterface
from numpy import array, zeros, pi, ones, cos, sin, mean
from pylab import concatenate, figure, show, ion, ioff, pause,xlabel, ylabel, plot, Circle, sqrt, arctan, arctan2, close
from copy import copy
from random import uniform, seed, sample, randint


[SH,EL] = [X,Y] = [0,1]
[SH_EXT, SH_FLEX, EL_EXT, EL_FLEX] = [0,1,2,3]

  
class Arm:
    #%% init
    def __init__(self, type, anim, graphs): # initialize variables
        self.type = type # 'randomOutput', 'dummyArm', 'musculoskeletal'
        self.anim = anim # whether to show arm animation or not
        self.graphs = graphs # whether to show graphs at the end


    ################################
    ### SUPPORT METHODS
    ################################

    # convert cartesian position to joint angles
    def pos2angles(self, armPos, armLen):
        x = armPos[0]
        y = armPos[1]
        l1 = armLen[0]
        l2 = armLen[1]
        elang = abs(2*arctan(sqrt(((l1 + l2)**2 - (x**2 + y**2))/((x**2 + y**2) - (l1 - l2)**2)))); 
        phi = arctan2(y,x); 
        psi = arctan2(l2 * sin(elang), l1 + (l2 * cos(elang)));
        shang = phi - psi; 
        return [shang,elang]

    # convert joint angles to cartesian position
    def angles2pos(self, armAng, armLen):        
        elbowPosx = armLen[0] * cos(armAng[0]) # end of elbow
        elbowPosy = armLen[0] * sin(armAng[0])
        wristPosx = elbowPosx + armLen[1] * cos(+armAng[0]+armAng[1]) # wrist=arm position
        wristPosy = elbowPosy + armLen[1] * sin(+armAng[0]+armAng[1])
        return [wristPosx,wristPosy] 

    #%% setTargetByID
    def setTargetByID(self, id, startAng, targetDist, armLen):
        startPos = self.angles2pos(startAng, armLen)
        if id == 0:
            targetPos = [startPos[0]+0.15, startPos[1]+0]
        elif id == 1:
            targetPos = [startPos[0]-0.15, startPos[1]+0]
        elif id == 2:
            targetPos = [startPos[0]+0, startPos[1]+0.15]
        elif id == 3:
            targetPos = [startPos[0]+0, startPos[1]-0.15]
        return targetPos

    #%% setupDummyArm
    def setupDummyArm(self):
        if self.anim:
            ion()
            self.fig = figure() # create figure
            l = 1.1*sum(self.armLen)
            self.ax = self.fig.add_subplot(111, autoscale_on=False, xlim=(-l/2, +l), ylim=(-l/2, +l)) # create subplot
            self.ax.grid()
            self.line, = self.ax.plot([], [], 'o-', lw=2)
            self.circle = Circle((0,0),0.04, color='g', fill=False)
            self.ax.add_artist(self.circle)

    #%% runDummyArm: update position and velocity based on motor commands; and plot
    def runDummyArm(self, dataReceived):
        friction = 0.5 # friction coefficient
        shang = (self.ang[SH] + self.angVel[SH] * self.interval/1000) #% update shoulder angle
        elang = (self.ang[EL] + self.angVel[EL] * self.interval/1000) #% update elbow angle
        if shang<self.minPval: shang = self.minPval # limits
        if elang<self.minPval: elang = self.minPval # limits
        if shang>self.maxPval: shang = self.maxPval # limits
        if elang>self.maxPval: elang = self.maxPval # limits
        elpos = [self.armLen[SH] * cos(shang), self.armLen[SH] * sin(shang)] # calculate shoulder x-y pos
        handpos = [elpos[X] + self.armLen[EL] * cos(shang+elang), elpos[Y] + self.armLen[EL] * sin(shang+elang)]
        shvel = self.angVel[SH] + (dataReceived[1]-dataReceived[0]) - (friction * self.angVel[SH])# update velocities based on incoming commands (accelerations) and friction
        elvel = self.angVel[EL] + (dataReceived[3]-dataReceived[2]) - (friction * self.angVel[EL])
        if self.anim:
            self.circle.center = self.targetPos
            self.line.set_data([0, elpos[0], handpos[0]], [0, elpos[1], handpos[1]]) # update line in figure
            self.ax.set_title('Time = %.1f ms, shoulder: pos=%.2f rad, vel=%.2f, acc=%.2f ; elbow: pos = %.2f rad, vel = %.2f, acc=%.2f' % (float(self.duration), shang, shvel, dataReceived[0] - (friction * shvel), elang, elvel, dataReceived[1] - (friction * elvel) ), fontsize=10)
            show(block=False)
            pause(0.0001) # pause so that the figure refreshes at every time step
        return [shang, elang, shvel, elvel, handpos[0], handpos[1]]

    #%% Reset arm variables so doesn't move between trials
    def resetArm(self, s, t):
        self.trial = self.trial + 1
        s.timeoflastreset = t
        if self.type == 'dummyArm':
            self.ang = list(self.startAng) # keeps track of shoulder and elbow angles
            self.angVel = [0,0] # keeps track of joint angular velocities
            self.motorCmd = [0,0,0,0] # motor commands to muscles
            self.error = 0 # error signal (eg. difference between )
            self.critic = 0 # critic signal (1=reward; -1=punishment)
            self.initArmMovement = self.initArmMovement + s.testTime
        

    def setPMdInput(self, s):
        for c in range(0, s.popnumbers[s.PMd], 2):
            try: 
                gid = s.popGidStart[s.PMd] + c # find gid of PMd 
                lid = s.gidDic[gid] # find local index corresponding to gid
                if (gid in s.targetPMdInputs[s.targetid]):  # if gid in PMdinputs for this target
                    #print "yes:",gid
                    s.cells[lid].interval=1000/s.maxPMdRate # set low interval (in ms as a function of rate)
                else: # if angle not in range -> low firing rate
                    s.cells[lid].interval=1000/s.minPMdRate # set high interval (in ms as a function of rate)
                    #print "no:",gid
            except:
                pass # local index corresponding to gid not found in this node

    #%% plot motor commands
    def RLcritic(self, t):
        if t > self.initArmMovement: # do not calculate critic signal in between trials
            # Calculate critic signal and activate RL (check synapses between nsloc->cells)
            RLsteps = int(self.RLinterval/self.interval)

            if len(self.errorAll) >= RLsteps:
                diff = self.error - mean(self.errorAll[-RLsteps:-1]) # difference between error at t and at t-(RLdt/dt) eg. t-50/5 = t-10steps
            else:
                diff = 0
            if diff < -self.minRLerror: # if error negative: LTP 
                self.critic = 1 # return critic signal to model.py so can update synaptic weights
            elif diff > self.minRLerror: # if error positive: LTD
                self.critic = -1
            else: # if difference not significant: no weight change
                self.critic = 0
        else: # if 
            self.critic = 0
        return self.critic

    #%% plot joint angles
    def plotTraj(self, filename):
        fig = figure() 
        l = 1.1*sum(self.armLen)
        ax = fig.add_subplot(111, autoscale_on=False, xlim=(-l/2, +l), ylim=(-l/2, +l)) # create subplot
        posX, posY = zip(*[self.angles2pos([x[SH],x[EL]], self.armLen) for x in self.angAll])
        ax.plot(posX, posY, 'r')
        targ = Circle((self.targetPos),0.04, color='g', fill=False) # target
        ax.add_artist(targ)
        ax.grid()
        ax.set_title('X-Y Hand trajectory')
        xlabel('x')
        ylabel('y')
        print 'saving '+filename
        fig.savefig(filename)

    #%% plot joint angles
    def plotAngs(self):
        fig = figure() 
        ax = fig.add_subplot(111) # create subplot
        sh = [x[SH] for x in self.angAll]
        el = [x[EL] for x in self.angAll]
        ax.plot(sh, 'r', label='shoulder')
        ax.plot(el, 'b', label='elbow')
        shTarg = self.pos2angles(self.targetPos, self.armLen)[0]
        elTarg = self.pos2angles(self.targetPos, self.armLen)[1]
        ax.plot(range(0,len(sh)), [shTarg] * len(sh), 'r:', label='sh target')
        ax.plot(range(0,len(el)), [elTarg] * len(el), 'b:', label='el target')
        ax.set_title('Joint angles')
        xlabel('time')
        ylabel('angle')
        ax.legend()

    #%% plot motor commands
    def plotMotorCmds(self):
        fig = figure() 
        ax = fig.add_subplot(111) # create subplot
        shext = [x[SH_EXT] for x in self.motorCmdAll]
        elext = [x[EL_EXT] for x in self.motorCmdAll]
        shflex = [x[SH_FLEX] for x in self.motorCmdAll]
        elflex = [x[EL_FLEX] for x in self.motorCmdAll]
        ax.plot(shext, 'r', label='sh ext')
        ax.plot(shflex, 'r:', label='sh flex')
        ax.plot(elext, 'b', label='el ext')
        ax.plot(elflex, 'b:', label='el flex')
        ax.set_title('Motor commands')
        xlabel('time')
        ylabel('motor command')
        ax.legend()

    #%% plot RL critic signal and error
    def plotRL(self):
        fig = figure() 
        ax = fig.add_subplot(111) # create subplot
        ax.plot(self.errorAll, 'r', label='error')
        ax.plot((array(self.criticAll)+1.0) * max(self.errorAll) / 2.0, 'b', label='RL critic')
        ax.set_title('RL critic and error')
        xlabel('time')
        ylabel('Error (m) / RL signal')
        ax.legend()

    ################################
    ### SETUP
    ################################
    def setup(self, s):#, nduration, loopstep, RLinterval, pc, scale, popnumbers, p): 
        self.duration = s.duration#/1000.0 # duration in msec
        self.interval = s.loopstep#/1000.0 # interval between arm updates in ,sec       
        self.RLinterval = s.RLinterval # interval between RL updates in msec
        self.minRLerror = s.minRLerror # minimum error change for RL (m)
        self.armLen = s.armLen # elbow - shoulder from MSM;radioulnar - elbow from MSM;  
        self.handPos = [0,0] # keeps track of hand (end-effector) x,y position
        self.handPosAll = [] # list with all handPos
        self.handVel = [0,0] # keeps track of hand (end-effector) x,y velocity
        self.handVelAll = [] # list with all handVel
        self.startAng = s.startAng # starting shoulder and elbow angles (rad) = natural rest position
        self.ang = list(self.startAng) # keeps track of shoulder and elbow angles
        self.angAll = [] # list with all ang
        self.angVel = [0,0] # keeps track of joint angular velocities
        self.angVelAll = [] # list with all angVel
        self.motorCmd = [0,0,0,0] # motor commands to muscles
        self.motorCmdAll = [] # list with all motorCmd
        self.targetDist = s.targetDist # target distance from center (15 cm)
        #self.targetid = 0 # target id (eg. 0=right, 1=left, 2=top, 3=bottom)
        self.targetidAll = [] # list with all targetid
        self.targetPos = self.setTargetByID(s.targetid, self.startAng, self.targetDist, self.armLen) # set the target location based on target id
        self.error = 0 # error signal (eg. difference between )
        self.errorAll = [] # list with all error
        self.critic = 0 # critic signal (1=reward; -1=punishment)
        self.criticAll = [] # list with all critic
        self.randDur = 0 # initialize explor movs duration
        self.initArmMovement = int(s.initArmMovement) # start arm movement after x msec
        self.trial = 0 # trial number

        # motor command encoding
        self.vec = h.Vector()
        self.cmdmaxrate = s.cmdmaxrate # maximum spikes for motor command (normalizing value)
        self.cmdtimewin = s.cmdtimewin # spike time window for shoulder motor command (ms)


        # proprioceptive encoding
        self.pStart = s.pStart # proprioceptive encoding first cell
        self.numPcells = s.numPcells # number of proprioceptive cells to encode shoulder and elbow angles
        self.prange = zeros((self.numPcells,2)) # range of values encoded by each P cell (proprioceptive tuning curve)
        self.minPval = s.minPval # min angle to encode
        self.maxPval = s.maxPval # max angle to encode
        self.minPrate = s.minPrate # firing rate when angle not within range
        self.maxPrate = s.maxPrate # firing rate when angle within range
        angInterval = (self.maxPval - self.minPval) / (self.numPcells - 2) * 2 # angle interval (times 2 because shoulder+elbow)
        currentPval = self.minPval
        for c in range(0,self.numPcells,2):
            self.prange[c,0] = currentPval # shoulder lower range
            self.prange[c,1] = currentPval + angInterval # shoulder higher range
            self.prange[c+1,0] = currentPval # elbow lower range
            self.prange[c+1,1] = currentPval + angInterval # elbow higher range
            currentPval += angInterval


        # initialize dummy or musculoskeletal arm 
        if s.rank == 0: 
            if self.type == 'dummyArm': 
                self.setupDummyArm() # setup dummyArm (eg. graph animation)
            elif self.type == 'musculoskeletal':  
                damping = 1 # damping of muscles (.osim parameter)
                shExtGain = 2  # gain factor to multiply force of shoulder extensor muscles (.osim parameter)
                shFlexGain = 1 # gain factor to multiply force of shoulder flexor muscles (.osim parameter)
                elExtGain = 1 # gain factor to multiply force of elbow extensor muscles (.osim parameter)
                elFlexGain = 0.8 # gain factor to multiply force of elbox flexor muscles (.osim parameter)
                # call function to initialize virtual arm params and run virtual arm C++ executable
                arminterface.setup(self.duration/1000.0, self.interval, self.startAng[SH], self.startAng[EL], self.targetPos[X], self.targetPos[Y], damping, shExtGain, shFlexGain, elExtGain, elFlexGain)
        
        # set PMd inputs
        if s.PMdinput == 'targetSplit': 
            self.setPMdInput(s) # set PMd inputs

    ################################          
    ### RUN     
    ################################
    def run(self, t, s): #pc, cells, gidVec, gidDic, cellsperhost=[], hostspikevecs=[]): 

        # Append to list the the value of relevant variables for this time step (only worker0)
        if s.rank == 0:     
            self.handPosAll.append(list(self.handPos)) # list with all handPos
            self.handVelAll.append(list(self.handVel))  # list with all handVel
            self.angAll.append(list(self.ang)) # list with all ang
            self.angVelAll.append(list(self.angVel)) # list with all angVel
            self.motorCmdAll.append(list(self.motorCmd)) # list with all motorCmd
            self.targetidAll.append(self.targetid) # list with all targetid
            self.errorAll.append(self.error) # error signal (eg. difference between )
            self.criticAll.append(self.critic) # critic signal (1=reward; -1=punishment)

        ############################
        # dummyArm or musculoskeletal: gather spikes for motor command
        ############################
        if self.type == 'dummyArm' or self.type == 'musculoskeletal': 
            ## Exploratory movements
            if s.explorMovs and t-s.timeoflastexplor >= self.randDur: # if time to update exploratory movement
                seed(s.id32('%d'%(int(t)+s.randseed))) # init seed
                self.randMus = int(uniform(0,s.nMuscles)) # select random muscle group
                self.randMul = uniform(s.explorMovsFactor/5,s.explorMovsFactor) # select random multiplier
                self.randDur = uniform(s.explorMovsDur/5, s.explorMovsDur) # select random duration
                s.timeoflastexplor = t

                if s.explorMovs == 1: # add random noise to EDSC+IDSC population
                    IDSCgids = array(s.motorCmdCellRange[self.randMus]) - int(s.popGidStart[s.EDSC]) + int(s.popGidStart[s.IDSC]) 
                    IDSCgidsInverse = [j for j in range(s.popGidStart[s.IDSC],s.popGidEnd[s.IDSC]+1) if j not in list(IDSCgids)]
                    for (i,x) in enumerate(s.backgroundsources): # for all background input netstims
                        if s.backgroundgid[i] in s.motorCmdCellRange[self.randMus] or s.backgroundgid[i] in list(IDSCgids): # if connected to chosen muscle cells
                            #print s.backgroundgid[i]
                            x.interval = (self.randMul*s.backgroundrateExplor)**-1*1e3  # increase firing
                        elif s.backgroundgid[i] in [y for z in range(s.nMuscles) if z != self.randMus for y in s.motorCmdCellRange[z]+IDSCgidsInverse]:
                            x.interval = s.backgroundrateMin**-1*1e3 # otherwise set to minimum
                    #if s.rank==0: print 'exploratory movement, randMus',self.randMus,' strength:',self.randMul,' duration:', self.randDur
                    #print 'IDSC cells:', IDSCgids   
                    #print 'IDSC inverse cells:', IDSCgidsInverse

                
                elif s.explorMovs == 2: # add random noise to EB5 population
                    self.targetCells = range(s.popGidStart[s.EB5], s.popGidEnd[s.EB5]+1) # EB5 cell gids
                    self.randNumCells = randint(1, int(s.explorCellsFraction*len(self.targetCells))) # num of cells to stimumales
                    self.randCells = sample(self.targetCells, int(self.randNumCells)) # select random gids
                    for (i,x) in enumerate(s.backgroundsources):  # for all input background netstims
                        if s.backgroundgid[i] in self.randCells:  # if connectd to selected random cells
                            x.interval = s.backgroundrateExplor**-1*1e3  # increase input
                        elif s.backgroundgid[i] in [y for y in self.targetCells if y not in self.randCells]:  # for the rest of cells
                            x.interval = s.backgroundrateMin**-1*1e3  # set to normal level
                    #if s.rank==0: 
                    #print 'Nodes:', s.rank,' - exploratory movement, numcells:',self.randNumCells,' strength:',self.randMul,' duration:', self.randDur, 'cells:', self.randCells    


            ## Reset arm and set target after every trial -start from center etc
            if s.trialReset and t-s.timeoflastreset > s.testTime: 
                self.resetArm(s, t)
                s.targetid = s.trialTargets[self.trial] # set target based on trial number
                self.targetPos = self.setTargetByID(s.targetid, self.startAng, self.targetDist, self.armLen) 
                if s.PMdinput == 'targetSplit': self.setPMdInput(s)


            ## Only move after initial period - avoids initial transitory spiking period (NSLOC sync spikes), and allows for variables with history to clear
            # can be justified as preparatory period (eg. watiing for go cue)
            if t > self.initArmMovement:
                ## Gather spikes #### from all vectors to then calculate motor command 
                for i in range(s.nMuscles):
                    cmdVecs = [array(s.hostspikevecs[x]) for x in range(s.cellsperhost) if (s.gidVec[x] in s.motorCmdCellRange[i])]
                    self.motorCmd[i] = sum([len(x[(x < t) * (x > t-self.cmdtimewin)]) for x in cmdVecs])
                    s.pc.allreduce(self.vec.from_python([self.motorCmd[i]]), 1) # sum
                    self.motorCmd[i] = self.vec.to_python()[0]       
            # else:
            #     for i in range(s.nMuscles): # stimulate all muscles equivalently so arm doesnt move
            #         self.motorCmd[i] = 0.2 * self.cmdmaxrate

                ## Calculate final motor command 
                if s.rank==0:  
                    self.motorCmd = [x / self.cmdmaxrate for x in self.motorCmd]  # normalize motor command 
                    if s.antagInh: # antagonist inhibition
                        if self.motorCmd[SH_EXT] > self.motorCmd[SH_FLEX]: # sh ext > sh flex
                            self.motorCmd[SH_FLEX] =  self.motorCmd[SH_FLEX]**2 / self.motorCmd[SH_EXT] / s.antagInh
                        elif self.motorCmd[SH_EXT] < self.motorCmd[SH_FLEX]: # sh flex > sh ext
                            self.motorCmd[SH_EXT] = self.motorCmd[SH_EXT]**2 / self.motorCmd[SH_FLEX] / s.antagInh
                        if self.motorCmd[EL_EXT] > self.motorCmd[EL_FLEX]: # el ext > el flex
                            self.motorCmd[EL_FLEX] = self.motorCmd[EL_FLEX]**2 / self.motorCmd[EL_EXT] / s.antagInh
                        elif self.motorCmd[EL_EXT] < self.motorCmd[EL_FLEX]: # el ext > el flex
                            self.motorCmd[EL_EXT] = self.motorCmd[EL_EXT]**2 / self.motorCmd[EL_FLEX] / s.antagInh
             

        ############################
        # ALL arms: Send motor command to virtual arm; receive new position; update proprioceptive population (ASC)
        ############################
        # Worker 0 sends motor commands and receives data from virtual arm
        #print "t=%f , self.initArmMovement=%f"%(t, self.initArmMovement)
        if s.rank == 0:
            if self.type == 'musculoskeletal': # MUSCULOSKELETAL
                try:
                    dataReceived = arminterface.sendAndReceiveDataPackets(t, self.interval, self.motorCmd[0], self.motorCmd[1], self.motorCmd[2], self.motorCmd[3])
                except:
                    dataReceived = [self.ang[SH], self.ang[EL]]
                if not dataReceived or dataReceived==[-3,3]:  # if error receiving packet
                    dataReceived = [self.ang[SH], self.ang[EL]]  # use previous packet
                    print 'Missed packet at t=%.2f',t
            elif self.type == 'dummyArm': # DUMMYARM
                dataReceived = self.runDummyArm(self.motorCmd) # run dummyArm
            elif self.type == 'randomOutput': # RANDOMOUTPUT
                dataReceived = [0,0] 
                dataReceived[0] = uniform(self.minPval, self.maxPval) # generate 2 random values  
                dataReceived[1] = uniform(self.minPval, self.maxPval)  
            # broadcast dataReceived  to other workers.   
            n = s.pc.broadcast(self.vec.from_python(dataReceived), 0) # convert python list to hoc vector for broadcast data received from arm
        else: # other workers
            n = s.pc.broadcast(self.vec, 0)  # receive shoulder and elbow angles from worker0 so can compare with cells in this worker
            dataReceived = self.vec.to_python()  
        if self.type == 'musculoskeletal':
            [self.ang[SH], self.ang[EL]] = dataReceived
            self.handPos = self.angles2pos(self.ang, self.armLen) 
            self.angVel[SH] = self.angVel[EL] = 0 
        else:
            [self.ang[SH], self.ang[EL], self.angVel[SH], self.angVel[EL], self.handPos[SH], self.handPos[EL]] = dataReceived # map data received to shoulder and elbow angles
        #[self.ang[SH], self.ang[EL], self.angVel[SH], self.angVel[EL]] = dataReceived # map data received to shoulder and elbow angles      
        
        #### Update proprio pop ASC
        for c in range(0, self.numPcells, 2):
            try: 
                id = s.gidDic[self.pStart + c] # find local index corresponding to gid
                if (self.ang[SH] >= self.prange[c,0] and self.ang[SH] < self.prange[c,1]):  # in angle in range -> high firing rate
                    s.cells[id].interval=1000/self.maxPrate # interval in ms as a function of rate
                else: # if angle not in range -> low firing rate
                    s.cells[id].interval=1000/self.minPrate # interval in ms as a function of rate
            except:
                pass # local index corresponding to gid not found in this node
            try: 
                id = s.gidDic[self.pStart + c + 1] # find local index corresponding to gid
                if (self.ang[EL] >= self.prange[c+1,0] and self.ang[EL] < self.prange[c+1,1]):  # in angle in range -> high firing rate
                    s.cells[id].interval=1000/self.maxPrate # interval in ms as a function of rate
                else: # if angle not in range -> low firing rate
                    s.cells[id].interval=1000/self.minPrate # interval in ms as a function of rate 
            except:
                pass # local index corresponding to gid not found in this node


        #### Calculate error between hand and target for interval between RL updates 
        if s.rank == 0 and self.initArmMovement: # do not update between trials
            #print 't=%.2f, xpos=%.2f'%(t,self.targetPos[X])
            self.error = sqrt((self.handPos[X] - self.targetPos[X])**2 + (self.handPos[Y] - self.targetPos[Y])**2)
            
        return self.critic


    ################################
    ### CLOSE
    ################################
    def close(self, s):             
        if self.type == 'randomOutput':
            print('\nClosing random output virtual arm...')

        if self.type == 'dummyArm':
            if s.explorMovs == 1: # remove explor movs related noise to cells
                for imus in range(s.nMuscles):
                    IDSCgids = array(s.motorCmdCellRange[self.randMus]) - int(s.popGidStart[s.EDSC]) + int(s.popGidStart[s.IDSC]) 
                    for (i,x) in enumerate(s.backgroundsources):
                        if s.backgroundgid[i] in s.motorCmdCellRange[imus]+list(IDSCgids):
                            x.interval = 0.0001**-1*1e3
                            x.noise = s.backgroundnoise # Fractional noise in timing
            elif s.explorMovs == 2: # remove explor movs related noise to cells
                for (i,x) in enumerate(s.backgroundsources):  # for all input background netstims
                    if s.backgroundgid[i] in self.targetCells:  # for the rest of cells
                        x.interval = s.backgroundrate**-1*1e3  # set to normal level

            if s.trialReset:
                s.timeoflastreset = 0
                self.initArmMovement = int(s.initArmMovement)

            if s.rank == 0:
                print('\nClosing dummy virtual arm ...') 

                if self.anim:
                    ioff() # turn interactive mode off
                    close(self.fig) # close arm animation graph 
                if self.graphs: # plot graphs
                    self.plotTraj(s.filename)
                    #self.plotAngs()
                    #self.plotMotorCmds()
                    #self.plotRL()
        
        if self.type == 'musculoskeletal':
            if s.explorMovs == 1: # remove explor movs related noise to cells
                for imus in range(s.nMuscles):
                    IDSCgids = array(s.motorCmdCellRange[self.randMus]) - int(s.popGidStart[s.EDSC]) + int(s.popGidStart[s.IDSC]) 
                    for (i,x) in enumerate(s.backgroundsources):
                        if s.backgroundgid[i] in s.motorCmdCellRange[imus]+list(IDSCgids):
                            x.interval = 0.0001**-1*1e3
                            x.noise = s.backgroundnoise # Fractional noise in timing
            elif s.explorMovs == 2: # remove explor movs related noise to cells
                for (i,x) in enumerate(s.backgroundsources):  # for all input background netstims
                    if s.backgroundgid[i] in self.targetCells:  # for the rest of cells
                        x.interval = s.backgroundrate**-1*1e3  # set to normal level

            if s.trialReset:
                s.timeoflastreset = 0
                self.initArmMovement = int(s.initArmMovement)

            if s.rank == 0:
                print('\nClosing dummy virtual arm ...') 
                arminterface.closeSavePlot(self.duration/1000.0, self.interval)

                if self.graphs: # plot graphs
                    self.plotTraj(s.filename)
                    #self.plotAngs()
                    self.plotMotorCmds()
                    self.plotRL()
        


    
    
