"""
server.py 

Interface between model and plexon 

Developed by giljael
Version: 2015feb14 modified by salvadord
"""

from glob import glob
from socket import *
from neuron import h # for working with DP cells
from multiprocessing import Process, Manager, Queue, Value, Lock
from threading import Thread

import struct
import time
import os
import sys
import Queue
import array
import math
import numpy as np
import traceback
import shared as s


### Copied plexon config here

# a queue between the server and the virtual arm model
queue = Manager().Queue()
currNeuronTime = Value('d', 0.0) # for NEURON time exchange
currQueueTime = Value('d', 0.0) # for queue time exchange
newCurrTime = Value('d', 0.0)
lock = Lock()

# When there is no data from the plexon system,
# the client will send 'exit' to the server and 
# terminate itserlf after timeOut * timeWnd time.
# ex) 100 * 500 = 50 seconds
timeOut = 500 #10000 

# header ID
NODATA = 0
DATA   = 1
EXIT   = 2
ALIVE   = 3
ACK    = 4
INITDATA = 5

# channel start
CH_START  = 1
# channel end 
CH_END    = 96
# unit end
UNIT_END  = 4

# data size
NODATA_SIZE = 4  # header ID + timeInterval
DATA_SIZE = (CH_END + 1) * 8 # 1 for binning window. 8 is double in Matlab
EXIT_SIZE   = 2  # only header ID
ACK_SIZE    = 2  # only header ID

# For Latency measure
O_END = 1
O_SND = 2
O_RCV = 3
O_FLT = 4


#####################################################################
#                Variables user may modify                          #
#####################################################################
# port number for sending initial data to the client from the server. 
# When it is changed, initPort in client.m should be changed as well.
initPort = 7869  
# port number for receiving spikes from the client
comPort = 9999   
# Time window for binning and summing spikes
binWnd = 100 # (ms)
autorun = 1  # autorun- 0: interactive mode 1: autorun upto
# 0: Using monkey spike, 1: Using original data to update DP cells.
isClosedLoop = 0 # 0: open loop w/o arm, 1: closed loop with arm
isOriginal = 0 # 0: cliff's model + the server process, 1: Just Cliff's model
numPMd = CH_END
isCommunication = 1 # 0: read spikes from a file by the server, 1: get spikes through the queue
localFileRead = 1 # 0: real communication and spikes delivery through the queue
                # 1:  the queue test reading spikes in a file at the serer side
# 0: No output, 1: print information to stdout as well as files
verbose = 0
timeMeasure = 0
#ackServerIP = "10.244.18.233" # windows at the ACIS Lab.
ackServerIP = "138.5.98.28" # windows at the Francis Lab. (XPC64)

isUdp = 0    # 0: TCP, 1: UDP
simMode = 0 # simMode- Offline mode(0),  online mode(1)
LR = 1000e3
unsortedSpkFilter = 0 # 0: counts unsorted unit, 1: filter unsorted unit 
syncSpkFilter = 0 # 0: default, no filtering, 1: filter spikes having identical timestamps, 2: filter spikes in a same time window.
isDp = 0     # 0: NSLOC, 1:DP
isLwc = 0    # 0: Heavy weight client, 1: light weight client
SPKNUM = 20 # number of spikes in a chunk
SPKSZ = 3 * SPKNUM + 1 # size of a List to store SPKNUM (CH_ID, UNIT_ID, TS), 1 for spikes in the chunk, and 1 for flag to indicate if spike remains in a chunk
TIMEOUT = 20 * 0.001 # it should be second
syncWnd = 0.001

# For latency measure 
qTimeList = []
deqTimeList = []

if verbose:
    fdtime = open('SpikeTimeStamp.tsv', 'w')
    fdtime.write('CH#\tUnit#\tTS\n')  
    fdtime2 = open('SpikeTimeStamp2.tsv', 'w')
    fdtime2.write('CH#\tUnit#\tTS\tSimTS\n')  
    fdtime3 = open('log.tsv', 'w') 
 
#####################################################################
#                Parameter validation                               #
#####################################################################
if isOriginal == 1:
    isCommunication = 0

if isCommunication == 0 or simMode == 1:
    localFileRead = 0 # queue test w/ no communication is useless

if isDp == 1: 
    if simMode == 1:
        LR = 500 # latency requirement (ms)
else: # NSLOC
    if simMode == 1:
        LR = 50

if simMode == 0:
    LR = 1000e3

if unsortedSpkFilter == 0:    
    UNIT_START = 0
else :
    UNIT_START = 1

# Print out server's information
def getServerInfo(): 
    if simMode == 1:
        fname = "Online/" 
    else:
        fname = "Offline/" 
    if isUdp == 1:
        fname += "UDP/"
    else:
        fname += "TCP/"
    if isDp == 1:
        fname += "DP/binning("
        if isLwc == 1:
            fname += "Lwc)/"
        else:
            fname += "Hwc)/"
    else:
        fname += "NSLOC/"
    if unsortedSpkFilter ==  1:
        fname += "unsortedSpkFilter("
        if isLwc == 1:
            fname += "Lwc)/"        
        else:
            fname += "Hwc)/"
    if syncSpkFilter:
        fname += "syncSpkFilter("
        if isLwc == 1:
            fname += "Lwc)/"        
        else:
            fname += "Hwc)/"
    if verbose:
        fname += "Verbose/"        
    print fname + "server is launched!!!"



# Find NetCon by gid for None->NetCon->NSLOC
def checkLocalIndexbyKey(dicName, key):
    try:
        index = dicName[key]
    except:
        index = -1
    return index
    
def feedQueue(qItem, theVerbose = 0):
    if isDp: # DP model
        currQTime = qItem[CH_END] * binWnd
    else:    # NSLOC model
        spkNum = qItem[SPKSZ - 1]        
        if spkNum == 0: # timeout item
            currQTime = qItem[SPKSZ - 2] * 1000 # sec -> ms
        else:
            currQTime = qItem[(spkNum - 1) * 3 + 2] * 1000 # sec -> ms
    queue.put(qItem)
    while 1:
        qsize = queue.qsize()
        if qsize <= 1:
            break
        with lock:
            currSimTime = currNeuronTime.value
        if verbose:
            print "[feedQueue] currQTime:", currQTime, "currSimTime: ", currSimTime, "LR: ", LR
        if (currQTime - currSimTime) > LR:   # Simulation is slow
            if qsize == queue.qsize():       # callback doesn't get an item in Q so far
                queue.get()                  # discard an item
                if verbose:
                    print "[feedQueue] An item is discared in Q"
        else:                                # simulation is fast
            break

#class Event(object):
class Event:
    def __init__(self, dir="data"):
        self.dir = dir
        if isDp == 1: # binned data
            self.qItem = [0] * (CH_END + 1)
            self.invl = binWnd
            self.vec = h.mua # mua : vector in Hoc            
        else:    # spikes
            self.qItem = [0] * (SPKSZ + 1) # = 3 * SPKNUM + 1 + Serial Number
            self.invl = 0.025 
        if pc.id() == 0:
            self.fih = h.FInitializeHandler(1, self.callback)
        else:
            self.fih = h.FInitializeHandler(1, self.callbackSlave)
        # for timing measurement           
        self.num = 0
        self.write = 1

        # for opto
        if isCommunication == 0 and pc.id == 0:
            if isDp == 0: # read spikes from a file by the server w/o communication
                self.fname = self.dir + "/spikePMd-6sec.tsv"
                self.fd = open(self.fname, "r")
                print "[Open ", self.fname, " for test]"
            else: # DP
                pass
                              
    # callback function for the DP (isDp = 1) and NSLOC (isDp = 0) model
    def callbackSlave(self):
        try:
            if isCommunication == 0: # No queue in the server process
                if isDp == 0: # NSLOC and spikes from a file w/o communication
                    pass
                else: # DP
                    pass
            # get an item from the queue. Raise exception when it fails
            else:  # DP and NSLOC with online and offline mode 
                try:              
                    nextInvl = self.invl
                    currSimTime = h.t 
                    newCurrTime.value = currSimTime                    
                    if isDp == 1:
                        self.qItem = queue.get()
                    else:
                        n = pc.broadcast(s.vec, 0)
                #except Queue.Empty as e:  # No item in Q
                except:  # No item in Q
                    if verbose:
                        print "[callbackSlave] No item in Q"
                else:
                    if isDp == 0 and not n == 0: #NSLOC
                        #self.qItem = vec.to_python()
                        if timeMeasure and self.write:
                            deqTimeList.append(time.time() - timer)
                            self.num += 1
                            if self.num == iteration:
                                self.write = 0
                                if not os.path.exists(self.dir):
                                    os.mkdir(self.dir)
                                fname = self.dir + "/NslocPullTimefile"
                                f1 = open(fname, "w+")
                                for item in deqTimeList:
                                    f1.write("%s\n" % item)
                                f1.close()
                                print "=======NslocPulltime printed!!!"
                        spkNum = int(s.vec[SPKSZ - 1])
                        # update current neuron time
                        if spkNum == 0: # timeout item
                            currSimTime = self.qItem[SPKSZ - 2] * 1000 + h.t # sec -> ms
                        else:
                            #currSimTime = self.qItem[(spkNum - 1) * 3 + 2] * 1000 # sec -> ms 
                            currSimTime = s.vec[(spkNum - 1) * 3 + 2] * 1000 # sec -> ms
                        # [0]:CH_ID, [1]:Unit_ID, [2]: Time_stamp
                        for i in range(spkNum):
                            #timeStamp = self.qItem[3 * i + 2] * 1000  # second -> ms
                            timeStamp = s.vec[3 * i + 2] * 1000  # second -> ms
                            if h.t <= timeStamp and timeStamp <= duration: # queue spikes in the NEURON queue and ignore old spikes
                                # Queue netcon event. CH_START = 1, CH_END = 96
                                #localIndex = checkLocalIndexbyKey(int(self.qItem[3 * i] - 1), innclDic)
                                localIndex = checkLocalIndexbyKey(s.innclDic, int(vec[3 * i] - 1))
                                if not localIndex == -1:
                                    #h.s.inncl.o(localIndex).event(timeStamp, 1)
                                    s.inncl[localIndex].event(timeStamp, 1)
                                if verbose:
                                    print "[CallbackSlave] ChID:", self.qItem[3 * i], "UnitID:", self.qItem[3 * i + 1], "Time:", self.qItem[3 * i + 2] * 1000, "t: ", h.t
                                    #fdtime.write(str(int(self.qItem[3*i])) + '\t' +str(int(self.qItem[3*i+1])) + '\t' +str('{:g}'.format(self.qItem[3*i+2])) + '\n')
                            else: # spike ignored. For dubug
                                if verbose:
                                    print "[CallbackSlave] ChID:", self.qItem[3 * i], "UnitID:", self.qItem[3 * i + 1], "Time:", self.qItem[3 * i + 2], "t: ", h.t
                                #fdtime2.write(str(int(self.qItem[3*i])) + '\t' +str(int(self.qItem[3*i+1])) + '\t' +str('{:g}'.format(self.qItem[3*i+2])) + '\t' + str(h.t/1000) + '\n')
                    # move t to currSimTime
                    #if currSimTime > h.t and currSimTime < duration:
                    if currSimTime > h.t:
                        if simMode == 1: # online mode
                            newCurrTime.value = currSimTime                          
                    else:
                        currSimTime = h.t
                        newCurrTime.value = currSimTime
                finally:
                    if verbose:
                        print "[CallbackSlave] currNeuronTime: ", currSimTime
        except:
            if isCommunication == 0:
                self.fd.close()
            if verbose:
                print "[CallbackSlave] exception occurs:", traceback.print_exc()
        finally: # update current neuron time
            if isCommunication == 0:
                pass                   
            else:
                if verbose:
                    print('[callback.h.t End(id= %i)] %.3f' %(pc.id(), h.t))                                
                if newCurrTime.value + nextInvl <= duration:
                    h.cvode.event(newCurrTime.value + nextInvl, self.callbackSlave)   
                    
    # callback function for the DP (isDp = 1) and NSLOC (isDp = 0) model
    def callback(self):
        try:
            if isCommunication == 0: # No queue in the server process
                if isDp == 0: # NSLOC and spikes from a file w/o communication
                    #for locals in self.fd:
                    for locals in self.fd:
                        localts = locals.split()
                        if localts[0] == '1': # spikes
                            if unsortedSpkFilter and localts[2] == '0': # filter unsorted spikes
                                continue 
                            else:
                                tt = float(localts[3]) * 1000
                                if tt > h.t:
                                    s.inncl[int(localts[1]) - 1].event(tt, 1)
                                    if verbose:
                                        fdtime.write(str(1) + '\t' + str(int(localts[1])) + '\t' +str(int(localts[2])) + '\t' +str('{:g}'.format(float(localts[3]))) + '\n') 
                else: # DP
                    pass
            # get an item from the queue. Raise exception when it fails
            else:  # DP and NSLOC with online and offline mode 
                try:                      
                    nextInvl = self.invl
                    currSimTime = h.t 
                    newCurrTime.value = currSimTime
                    if timeMeasure:
                        timer = time.time()   
                    if isDp == 1:
                        self.qItem = queue.get()
                    else:
                        self.qItem = queue.get(False) # Q has an item?
                        n = pc.broadcast(s.vec.from_python(self.qItem), 0) # convert python list to hoc vector
                except Queue.Empty as e:  # No item in Q
                    n = pc.broadcast(s.emptyVec, 0)
                    if verbose:
                        print "[callback] No item in Q"
                else:
                    if isDp == 1:
                        if timeMeasure and self.write:                 
                                deqTimeList.append(time.time() - timer) 
                                self.num += 1
                                if self.num == iteration:
                                    self.write = 0                                                  
                                    if not os.path.exists(self.dir):
                                        os.mkdir(self.dir)
                                    fname = self.dir + "/DpPullTimefile"
                                    f1 = open(fname, "w+")
                                    for item in deqTimeList:
                                        f1.write("%s\n" % item)
                                    f1.close()
                                    print "=======DpPull time printed!!!"
                        # for debug
                        #if 0 and row > 0:#verbose:
                        #    f_handle = file('spk_rcv.txt', 'a')
                        #    for item in self.qItem:
                        #        f_handle.write("%d " % item)
                        #    f_handle.write("\n")
                        #    f_handle.close()                        
                        currSimTime = self.qItem[CH_END] * binWnd
                        if self.qItem[0] == -1: # timeout message in Q
                            print "[callback-DP] timeout message"
                            h.setUpdateDPzero() #h.updateDpWithZero()
                        else:                 # data in a queue item in Q
                            # Convert the python list to the hoc vector (h.mua)
                            self.vec = self.vec.from_python(self.qItem) 
                            h.updateDpWithMua()
                    else: #NSLOC
                        if timeMeasure and self.write:                 
                            deqTimeList.append(time.time() - timer) 
                            self.num += 1
                            if self.num == iteration:
                                self.write = 0                                                  
                                if not os.path.exists(self.dir):
                                    os.mkdir(self.dir)
                                fname = self.dir + "/NslocPullTimefile"
                                f1 = open(fname, "w+")
                                for item in deqTimeList:
                                    f1.write("%s\n" % item)
                                f1.close()
                                print "=======NslocPulltime printed!!!"
                        spkNum = self.qItem[SPKSZ - 1]
                        # update current neuron time
                        if spkNum == 0: # timeout item
                            currSimTime = self.qItem[SPKSZ - 2] * 1000 + h.t # sec -> ms
                        else:
                            currSimTime = self.qItem[(spkNum - 1) * 3 + 2] * 1000 # sec -> ms
                        # [0]:CH_ID, [1]:Unit_ID, [2]: Time_stamp
                        for i in range(spkNum):
                            timeStamp = self.qItem[3 * i + 2] * 1000  # second -> ms                             
                            if h.t <= timeStamp and timeStamp <= duration: # queue spikes in the NEURON queue and ignore old spikes
                                # Queue netcon event. CH_START = 1, CH_END = 96
                                localIndex = checkLocalIndexbyKey(s.innclDic, int(self.qItem[3 * i] - 1))
                                if not localIndex == -1:
                                    s.inncl[localIndex].event(timeStamp, 1)  
                                if verbose:     
                                    print "[Callback] ChID:", self.qItem[3 * i], "UnitID:", self.qItem[3 * i + 1], "Time:", self.qItem[3 * i + 2] * 1000, "t: ", h.t         
                                    #fdtime.write(str(int(self.qItem[3*i])) + '\t' +str(int(self.qItem[3*i+1])) + '\t' +str('{:g}'.format(self.qItem[3*i+2])) + '\n')
                            else: # spike ignored. For dubug
                                if verbose:
                                    print "[Callback] ChID:", self.qItem[3 * i], "UnitID:", self.qItem[3 * i + 1], "Time:", self.qItem[3 * i + 2], "t: ", h.t
                                    #fdtime.write(str(int(self.qItem[3*i])) + '\t' +str(int(self.qItem[3*i+1])) + '\t' +str('{:g}'.format(self.qItem[3*i+2])) + '\t' + str('{:g}'.format(h.t/1000)) + '\n')
                    # move t to currSimTime
                    if currSimTime > h.t:# and currSimTime < duration:
                        if simMode == 1: # online mode                           
                            newCurrTime.value = currSimTime
                    else:
                        currSimTime = h.t  
                        newCurrTime.value = currSimTime
                finally:
                    with lock:
                        currNeuronTime.value = currSimTime # (ms)
                        if verbose:
                            print "[Callback] currNeuronTime: ", currSimTime, nextInvl
        except:
            if isCommunication == 0:
                self.fd.close()
            if verbose:
                print "[Callback] exception occurs:", traceback.print_exc()
        finally: # update current neuron time
            if isCommunication == 0:
                pass
            else:
                if newCurrTime.value + nextInvl <= duration:
                    h.cvode.event(newCurrTime.value + nextInvl, self.callback)    
                if verbose:
                    print('[callback.h.t End(id= %i)] %.3f' %(pc.id(), h.t))                   
                    fdtime2.write('Invl: ' + str(nextInvl) + '\t' + 'h.t + Invl: ' + str(h.t + nextInvl) + '\n')
                    fdtime3.write('invl, h.t + nextInvl: ' + str(nextInvl) + ' ' + str(h.t + nextInvl) + '\n')                              

# Connect python server to plexon client.
# It waits for receiving an "ALIVE" message from the client.
# It conducts a shake-handing process to exchange parameters.
def nrn_py_connectPlxClient():
    try:
        # Set the socket parameter for initial handshaking with client
        host = "" # all available interfaces
        buf = 4096
        addr = (host, initPort)
        Sock = socket(AF_INET, SOCK_DGRAM)
        Sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        Sock.bind(addr)
        # receive ALIVE from the client

        data, addr = Sock.recvfrom(buf)
        print data
        dataLen = len(data)
        dlen = dataLen / 2
        if dataLen == 2:
            cdata = struct.unpack('H' * dlen, data)           
            if cdata[0] == ALIVE:
                if verbose:
                    print "I received ALIVE"
                # send INITDATA to the client
                a = array.array('H')
                a.extend([INITDATA, comPort, isUdp, isDp, isLwc, binWnd, timeOut, unsortedSpkFilter, syncSpkFilter, verbose])
                Sock.sendto(a.tostring(), addr)
                if verbose:
                    print "I sent INITDATA"
                data, addr = Sock.recvfrom(buf)
                dataLen = len(data)
                dlen = dataLen / 2
                cdata = struct.unpack('H' * dlen, data)
                if cdata[0] == ACK:                           
                    print "Connection success!!!"        
        else:
            print "ERROR: Connection failure!!!"
            raise
        Sock.close()           
            
        # Create socket and bind to address for spike exchange
        addr = (host, comPort)
        if isUdp:
            Sock = socket(AF_INET, SOCK_DGRAM)
            Sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)         
            Sock.bind(addr)        
            return (Sock, 0, 0)
        else:
            Sock = socket(AF_INET, SOCK_STREAM)
            Sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)        
            Sock.bind(addr)
            Sock.listen(1)
            conn, addr = Sock.accept()
            return (Sock, conn, addr)
    except:
        print "[nrn_py_connectPlxClient] exception occurs:", sys.exc_info()[0]
        sys.exit(0)
        

# Clarify spikes and external events.
# length(cdata) = drows * 4 fields : |data type|ch#|unit#|TS|
# this function returns two arrays for spikes and external events
def nrn_py_clarifyEvt(cdataNp):
    try:
        spkArr = np.zeros((0, 4))
        evtArr = np.zeros((0, 4))
        row, col = cdataNp.shape
        if row > 0:
            spkArr = cdataNp[cdataNp[:, 0] == 1] # spikes
            evtArr = cdataNp[cdataNp[:, 0] == 4] # external events
    except:
        print "[nrn_py_clarifyEvt] exception occurs:", sys.exc_info()[0]
    finally:        
        return (spkArr, evtArr)

# filter system events
def nrn_py_filterSysEvt(evtArr):
    try:
        newEvtArr = np.zeros((0, 4))
        row, col = evtArr.shape
        if row > 0:
            newEvtArr = evtArr[evtArr[:,1] == 257]
        if verbose:
            print "nrn_py_filterSysEvt returns"
    except:
        print "[nrn_py_filterSysEvt] exception occurs:", sys.exc_info()[0]
    finally:        
        return newEvtArr
    
    
# reorder spikes 
# orderedArr = nrn_py_reorder(spkArr)
def nrn_py_reorder(spkArr):
    if not hasattr(nrn_py_reorder, "keptArr"):
        nrn_py_reorder.keptArr = np.zeros((0, 4)) # this is a static numpy array        
    try:
        row, col = nrn_py_reorder.keptArr.shape
        orderedArr = np.zeros((0, 4))
        if row > 0:
            maxTS = nrn_py_reorder.keptArr[row - 1][3]
        else:
            maxTS = 0
        #concatenates   
        newArr = np.concatenate((nrn_py_reorder.keptArr, spkArr), axis = 0)
        row, col = newArr.shape
        if row > 0:
            # reorder by timestamps
            newArr = newArr[newArr[:, 3].argsort()]
            nrn_py_reorder.keptArr = newArr[newArr[:,3] > maxTS]
            orderedArr = newArr[newArr[:, 3] <= maxTS]
    except:
        print "[nrn_py_reorder] exception occurs:", sys.exc_info()[0]
    finally:
        return orderedArr
   
# Filter sync spikes
# syncSpkFilter = 1: filter spikes having same timestamp
# syncSpkFilter = 2: filter spikes in a sync window [syncWnd * x, syncWnd * (x + 1))
def nrn_py_filterSyncSpk(spkArr):
    if not hasattr(nrn_py_filterSyncSpk, "FRem"):
        nrn_py_filterSyncSpk.FRem = np.zeros((0, 4))
    if not hasattr(nrn_py_filterSyncSpk, "jValue"):
        nrn_py_filterSyncSpk.jValue = 0
    try:
        newFltdArr = np.zeros((0, 4))
        if syncSpkFilter == 1:
            row, col = spkArr.shape
            if row > 0:
                if row == 1: # one element in spkArr
                    newFltdArr = spkArr
                else: # more than one in spkArr   
                    sync = 0
                    baseValue = np.array(spkArr[0], ndmin = 2) # first elem in spkArr           
                    for ii in range(1, row): # 1, 2, 3, ..., m-1
                        if baseValue[0][3] != spkArr[ii][3]:
                            if sync == 0:
                                newFltdArr = np.concatenate((newFltdArr, baseValue), axis = 0)                            
                            else:
                                sync = 0
                        else:
                            sync = 1
                        baseValue = np.array(spkArr[ii], ndmin = 2)                
                    if sync == 0:
                        newFltdArr = np.concatenate((newFltdArr, baseValue), axis = 0)
        else:
            # filtering spikes in a same sync window greater than 0.00025 (ms)
            if syncSpkFilter == 2:
                newArr = np.concatenate((nrn_py_filterSyncSpk.FRem, spkArr), axis = 0)
                row, col = newArr.shape
                if row > 0:
                    # sync window size is syncWnd
                    # find the biggest "j"
                    maxTS = newArr[row - 1][3] 
                    newJ = nrn_py_filterSyncSpk.jValue + 1
                    while 1:
                        if syncWnd * (newJ - 1) <= maxTS and maxTS < (syncWnd * newJ): 
                            break
                        else:
                            newJ += 1
                    nrn_py_filterSyncSpk.FRem = newArr[newArr[:, 3] >= syncWnd * (newJ - 1)]
                    for ii in range(nrn_py_filterSyncSpk.jValue, newJ - 1):
                       newArr = newArr[newArr[:, 3] >= syncWnd * ii]
                       temp = newArr[newArr[:, 3] < syncWnd * (ii + 1)]
                       row, col = temp.shape
                       if row == 1:
                           newFltdArr = np.concatenate((newFltdArr, temp), axis = 0)  
                    nrn_py_filterSyncSpk.jValue = newJ - 1
            else:
                print "Wrong filtering options"
    except:
        print "[nrn_py_filterSyncSpk] exception occurs:", sys.exc_info()[0]
    finally:            
        return newFltdArr


def nrn_py_filterUnsortedSpk(spkArr):
    try:
        newFltdArr = np.zeros((0, 4))
        row, col = spkArr.shape
        if row > 0:
            newFltdArr = spkArr[spkArr[:, 2] > 0]
    except:
        print "[nrn_py_filterUnsortedSpk] exception occurs:", sys.exc_info()[0]
    finally:
        return newFltdArr    

##
# mua, binningComplete = nrn_py_binSpk(spkArr, binStart, timeoutFlag)
# Here mua is a numpy array, so it should be converted to python list.
def nrn_py_binSpk(spkArr, binStart, timeoutFlag):    
    try:
        # MUA in 1st, and 2nd time interval
        if not hasattr(nrn_py_binSpk, "binnedMsg"):
            nrn_py_binSpk.binnedMsg = np.zeros((CH_END + 1, 1))  # 96 channel + binWnd  
        if not hasattr(nrn_py_binSpk, "dataHave"):
            nrn_py_binSpk.dataHave = 0
        if not hasattr(nrn_py_binSpk, "BRem"):
            nrn_py_binSpk.BRem = np.zeros((0, 4)) # spikes
            
        #if unsortedSpkFilter == 0:
        #    UNIT_START = 0
        #else:
        #    UNIT_START = 1    
                        
        newBinnedMsg = np.zeros((CH_END + 1, 1))
        binningComplete = 0
        binEnd = (binStart + binWnd)/1000.0
        binStart = binStart/1000.0
        
        # concatenate
        newArr = np.concatenate((nrn_py_binSpk.BRem, spkArr), axis = 0)  
        nrn_py_binSpk.BRem = np.zeros((0, 4))
        row, col = newArr.shape
        if row > 0:
            nrn_py_binSpk.BRem = newArr[newArr[:, 3] >= binEnd]
            newArr = newArr[newArr[:, 3]< binEnd]
            row, col = newArr.shape  
            if row > 0:
                for j in range(row):       
                    channelID = newArr[j][1]
                    unitID = newArr[j][2]
                    timeStamp = newArr[j][3] #(ms)
                    #Timestamp is in the current time interval            
                    if binStart <= timeStamp and timeStamp < binEnd:
                        if CH_START <= channelID and channelID <= CH_END:   
                            if UNIT_START <= unitID and unitID <= UNIT_END:
                                nrn_py_binSpk.dataHave += 1
                                # Update spike counts/ch (MUA)
                                nrn_py_binSpk.binnedMsg[channelID - 1] += 1
        row, col = nrn_py_binSpk.BRem.shape
        if row > 0 or timeoutFlag == 1:
            binningComplete = 1
            if nrn_py_binSpk.dataHave:
                newBinnedMsg = nrn_py_binSpk.binnedMsg
                nrn_py_binSpk.dataHave = 0
                nrn_py_binSpk.binnedMsg = np.zeros((CH_END + 1, 1))
    except:
        print "[nrn_py_binSpk] exception occurs:", sys.exc_info()[0]
    finally: 
        return (newBinnedMsg, binningComplete)


##
# The LWC server with the Lightweight client which sends raw data to the server
# port: port number for UDP server
# binWnd: choose proper time window in ms. Ex) 100, 200, ... 
# verbose: 1 prints information useful for debugging
# Received data: <<data type|channel#|unit#|timestamps in seconds>>
def nrn_py_interfaceDpLwc(dir):
    print "nrn_py_interfaceDpLwc running..." 
    
    # MUA per channel in a binWnd: [spikes in ch0, spikes in ch1, ..., spikes in ch96, timeInterval]
    mua = [0] * (CH_END + 1)
    buf = 4096
    if verbose:
        # Remove previous data files
        if isUdp:
            fname = "Udp"        
        else:
            fname = "Tcp"               
        for fileRemove in glob('*LWC*.tsv'):
            os.unlink(fileRemove)
        f1 = open(fname + "LWCTS.tsv", "w+")
        f1.write('Type\tCH#\tUnit#\tTS\n')     
        f2 = open(fname + "LWC2.tsv", "w+")
        f2.write('IntervalEnd\tSpikes in all CHs\tTotal spikes\n')
        f3 = open(fname + "LWCMua.tsv", "w+")
        f3.write('IntervalEnd\tMUA/Ch\n')
        f4 = open(fname + "LWCSua.tsv", "w+")
        f4.write('IntervalEnd\tSUA/Ch\n')
        totalSpikeCnt = 0
        validSpikeCnt = 0
        spikePerTS = 0 # spike counts per timestamp
        totalRcvBytes = 0
        a = time.time()
    
    # connect to Plexon client
    Sock, conn, addr = nrn_py_connectPlxClient()        
    SN = 1 # serial number
    lastEndTS = 0.0 # second
    binStart = 0
    
    if timeMeasure:
        mAddr0 = (ackServerIP, measurePort0)
        mAddr1 = (ackServerIP, measurePort1)
        mAddr2 = (ackServerIP, measurePort2)
        mAddr3 = (ackServerIP, measurePort3)
        totalMUA = 0

        mSock = socket(AF_INET, SOCK_DGRAM)
        mSock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)           
        mA = array.array('H') 
        mA.extend([0])      
        fTimeNum = 1
        bTimeList = []

    # Rcv messages from the client
    while 1:
        if verbose:
            getTime1 = time.time()   
        if isUdp:
            data, addr = Sock.recvfrom(buf)    
        else:
            data = conn.recv(buf)
        if verbose:
            f3.write("gTime1: " + str(time.time() - getTime1) + "\t")
        dataHave = 0        
        dataLen = len(data)  
        if data == 'exit': 
            print "Client has exited!"
            if verbose:
                print "Total spikes: ", totalSpikeCnt, "Valid spikes: ", validSpikeCnt
                f1.write('Total spikes: ' + str(totalSpikeCnt) + '\tValid spikes: ' + str(validSpikeCnt) + '\n')
                f2.write('Valid spikes: ' + str(validSpikeCnt) + '\n')                                                                                       
                f1.close()
                f2.close()                                                            
            # close socket & generating exit and queue it
            Sock.close()
            sys.exit(0)
        # The client sends data (>4) or a "NODATA" message when timeout occurs (==4)
        elif dataLen >= 4:
            if verbose:
                getTime2 = time.time()
            timeoutFlag = 0
            if dataLen == 4:
                cdataNp = np.zeros((0, 4))
                timeoutFlag = 1
                if verbose:
                    print "No data"   
            else:
                if not isUdp:
                    while dataLen % 32 != 0: # For avoiding errors because of MSS in TCP    
                        data += conn.recv(buf)
                        dataLen = len(data)                      
                dlen = dataLen / 8 # double : 8 bytes         
                drows = dlen / 4   # 4 fields : |data type|ch#|unit#|TS|
                cdata = struct.unpack('d' * dlen, data)
                cdataNp = np.asarray(cdata).reshape(drows, 4) # convert tuple to 2D numpy array
            if timeMeasure:                                                       
                mA[0] = O_RCV  
                mSock.sendto(mA.tostring(), mAddr3)

                #### for filtering
                mA[0] = O_SND  
                mSock.sendto(mA.tostring(), mAddr1)
                ####
            # filtering 
            if syncSpkFilter > 0 and isLwc == 1:
                cdataNp = nrn_py_filterSyncSpk(cdataNp)
            if unsortedSpkFilter == 1 and isLwc == 1:
                cdataNp = nrn_py_filterUnsortedSpk(cdataNp);
            if timeMeasure:                                                       
                #### for filtering
                mA[0] = O_RCV  
                mSock.sendto(mA.tostring(), mAddr1)
                ####
            # binning (Lwc)
            if isDp == 1 and isLwc == 1: # binning in the DP model with the HWC mode
                if timeMeasure:
                    mA[0] = O_SND  
                    mSock.sendto(mA.tostring(), mAddr2)
                mua, binningComplete = nrn_py_binSpk(cdataNp, binStart, timeoutFlag)
                if binningComplete == 1:
                    row, col = mua.shape
                    mua = mua[:, 0].tolist() # [[],[],..,[]] -> [, , ,..., ]
                    if row == 0:
                        mua = [-1] * (CH_END + 1) # for no mua data
                    mua[CH_END] = (binStart + binWnd) / binWnd # binning window
                    binStart = binStart + binWnd;
                    if verbose:
                        print "Client sends a NODATA message!"                
                        timeStamp = cdata[1]
                        totalRcvBytes += NODATA_SIZE                              
                        f1.write(str(timeStamp) + '\n')  
                        f2.write(str(timeStamp) + '\t' + str(spikePerTS) + '\t' + str(totalSpikeCnt) + '\t' + str(NODATA_SIZE) + '\n')
                        qtime = time.time()
                    if timeMeasure: 
                        mA[0] = O_RCV  
                        mSock.sendto(mA.tostring(), mAddr2)
                        #mA[0] = O_END                     
                        #mSock.sendto(mA.tostring(), mAddr)      
                        timer = time.time()

                    feedQueue(mua, verbose) # add 0 + timeStamp to the queue

                    if timeMeasure: # timing measure 
                        totalMUA +=1
                        if totalMUA <= iteration:                            
                            qTimeList.append(time.time() - timer)
                        if totalMUA == iteration + 1:
                            if not os.path.exists(dir):
                                os.mkdir(dir)
                            fname = dir + "/LwcDpPushTimeFile"
                            f1 = open(fname, "w+")
                            for item in qTimeList:
                                f1.write("%s\n" % item)
                            f1.close()  
                            print "====LwcDp push"                  

                    if verbose:
                        a = time.time() - qtime                 
                    if 0:
                        print "No data"                          
                        
######################################################################
# For DP-HWC mode
# The HWC server with the Heavyweight client which sends processed data to the server
# Received data: <<MUAofCH1|SUA0ofCH1|SUA1ofCH1|SUA2ofCH1|SUA3ofCH1|SUA4ofCH1|...|Timestamps/TIME_WND>>
def nrn_py_interfaceDpHwc(dir):
    print "nrn_py_interfaceDpHwc running..." 
    # MUA per channel in a binWnd: [spikes in ch0, spikes in ch1, ..., spikes in ch96, timeInterval]
    mua = [0] * (CH_END + 1)
    buf = 4096
    
    if verbose:                  
        # Remove previous data files
        if isUdp:
            fname = "Udp"        
        else: 
            fname = "Tcp"
        for fileRemove in glob('*HWC*.tsv'):
            os.unlink(fileRemove)
        f1 = open(fname + "HWCMua.tsv", "w+")
        f1.write('IntervalEnd\tMUA/ch\n')
        f2 = open(fname + "HWC2.tsv", "w+")
        f2.write('IntervalEnd\tSpikes in all CHs\tTotal spikes\n')
        f3 = open(fname + "HWCSua.tsv", "w+")
        f3.write('IntervalEnd\tSUA/Ch\n')  
        totalSpikeCnt = 0
        spikePerTS = 0 # spike counts per timestamp
        totalRcvBytes = 0
        validSpikeCnt = 0
        a = time.time()
    
    # connect to Plexon client
    Sock, conn, addr = nrn_py_connectPlxClient()        
    SN = 1 # serial number
    lastEndTS = 0.0 # second
    
    # Rcv messages from the client
    if timeMeasure:
        totalMUA = 0 
        mAddr0 = (ackServerIP, measurePort0)
        mAddr1 = (ackServerIP, measurePort1)
        mAddr2 = (ackServerIP, measurePort2)
        mAddr3 = (ackServerIP, measurePort3)
        mSock = socket(AF_INET, SOCK_DGRAM)
        mSock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)           
        mA = array.array('H') 
        mA.extend([0])        
        number = 1        
    while 1:
        if verbose:
            getTime1 = time.time()   
        if isUdp:
            data, addr = Sock.recvfrom(buf)    
        else:
            data = conn.recv(buf)
        if verbose:
            f3.write("gTime1: " + str(time.time() - getTime1) + "\t")
        dataHave = 0        
        dataLen = len(data)  
        if data == 'exit': 
            print "Client has exited!"
            if verbose:
                print "Total spikes: ", totalSpikeCnt, "Valid spikes: ", validSpikeCnt
                f1.write('Total spikes: ' + str(totalSpikeCnt) + '\tValid spikes: ' + str(validSpikeCnt) + '\n')
                f2.write('Valid spikes: ' + str(validSpikeCnt) + '\n')                                                                                       
                f1.close()
                f2.close()                                                            
            # close socket & generating exit and queue it
            Sock.close()
            sys.exit(0)
        # The client sends data (>4) or a "NODATA" message when timeout occurs (==4)
        elif dataLen >= 4:
            if verbose:
                getTime2 = time.time()
            if dataLen == 4:
                #'H': unsigned short (2bytes)        
                cdata = struct.unpack('H' * 2, data) 
                mua = [-1] * (CH_END + 1)
                mua[CH_END] = cdata[1] # binning window
                if verbose:
                    print "Client sends a NODATA message!"                
                    timeStamp = cdata[1]
                    totalRcvBytes += NODATA_SIZE                              
                    f1.write(str(timeStamp) + '\n')  
                    f2.write(str(timeStamp) + '\t' + str(spikePerTS) + '\t' + str(totalSpikeCnt) + '\t' + str(NODATA_SIZE) + '\n')
                    qtime = time.time()
                feedQueue(mua, verbose) # add 0 + timeStamp to the queue
                if verbose:
                    a = time.time() - qtime                 
                if 0:
                    print "No data"  
            else:
                if not isUdp:
                    # DATA_SIZE = (CH_END + 1) * 8 # 1 for binning window. 8 is double in Matlab
                    while dataLen < DATA_SIZE: # For avoiding errors because of MSS in TCP    
                        data += conn.recv(buf)
                        dataLen = len(data)                      
                dlen = dataLen / 8 # double : 8 bytes # [ch1|ch2|...|ch96|binning window] 
                mua = struct.unpack('d' * dlen, data)

                if timeMeasure:    
                    mA[0] = O_RCV  
                    mSock.sendto(mA.tostring(), mAddr3)                      
                    timer = time.time()                                                  

                feedQueue(mua, verbose)        

                if timeMeasure: # timing measure
                    totalMUA +=1
                    if totalMUA <= iteration:
                        qTimeList.append(time.time() - timer)
                    if totalMUA == iteration + 1:
                        if not os.path.exists(dir):
                            os.mkdir(dir)
                        fname = dir + "/HwcDpPushTimeFile"
                        f1 = open(fname, "w+")
                        for item in qTimeList:
                            f1.write("%s\n" % item)
                        f1.close()  
	                print "==========HwcDpPushTimeFile"

                if verbose:
                    totalRcvBytes += DATA_SIZE
                    # for verification between client and server    
                    timeStamp = cdata[dataOffset + 1 + CH_END * 6] * binWnd 
                    f3.write(str(timeStamp)) 
                    # print MUA/ch only
                    f1.write(str(timeStamp))
                    for i in range(CH_END):
                        spikePerTS += mua[i]
                        f1.write('\t' + str(mua[i])) # 6=> ch:unit0:unit1:unit2:unit3:unit4
                        for j in range(UNIT_END + 1):
                            f3.write('\t' + str(cdata[dataOffset + 1 + i * 6 + 1 + j])) 
                    f1.write('\n')                  
                    f3.write('\n')                
                    totalSpikeCnt += spikePerTS
                    f2.write(str(timeStamp) + '\t' + str(spikePerTS) + '\t' + str(totalSpikeCnt) + '\t' + str(DATA_SIZE) + '\n')
                    spikePerTS = 0                     

#########################################################################################
# The server with the Lightweight client which sends raw data to the server
# It does't do the binning process, and just queues a chunk of spikes (CHID, UNITID, TS). 
# Received data: <<data type|channel#|unit#|timestamps in seconds>>
def nrn_py_interfaceNsloc(dir):
    print "[nrn_py_interfaceNsloc running...]" 
    # Monkey spike: [Channel ID, Unit ID, timestamp]
    spk = [0] * (SPKSZ + 1) # = 3 * SPKNUM + 1 + Serial Number 
    buf = 4096
    
    if verbose:
        # Remove previous data files
        if isUdp:
            fname = "Udp"        
        else:
            fname = "Tcp"               
        for fileRemove in glob('*NS*.tsv'):
            os.unlink(fileRemove)
        f1 = open(fname + "NSTS.tsv", "w+")
        f1.write('Type\tCH#\tUnit#\tTS\n')   
        f2 = open(fname + "NSValidTS.tsv", "w+")
        f2.write('CH#\tUnit#\tTS\n')    
        f3 = open(fname + "NSValidTS2.tsv", "w+")
        f3.write('CH#\tUnit#\tTS\n')              
        totalSpikeCnt = 0
        validSpikeCnt = 0
        a = time.time()
    
    
    # connect to Plexon client
    Sock, conn, addr = nrn_py_connectPlxClient()        
    SN = 1 # serial number
    lastEndTS = 0.0 # second
     
    if timeMeasure:
        totalMUA = 0
        mAddr0 = (ackServerIP, measurePort0)
        mAddr1 = (ackServerIP, measurePort1)
        mAddr2 = (ackServerIP, measurePort2)
        mAddr3 = (ackServerIP, measurePort3)
        mSock = socket(AF_INET, SOCK_DGRAM)
        mSock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)           
        mA = array.array('H') 
        mA.extend([0])   
        bTimeList = []  
        number = 1  
    # Rcv messages from the client
    while 1:
        if verbose:
            getTime1 = time.time()   
        if isUdp:
            data, addr = Sock.recvfrom(buf)    
        else:
            data = conn.recv(buf)
        if verbose:
            f3.write("gTime1: " + str(time.time() - getTime1) + "\t")
        dataHave = 0        
        dataLen = len(data)  
        if data == 'exit': 
            print "Client has exited!"
            if verbose:
                print "Total spikes: ", totalSpikeCnt, "Valid spikes: ", validSpikeCnt
                f1.write('Total spikes: ' + str(totalSpikeCnt) + '\tValid spikes: ' + str(validSpikeCnt) + '\n')
                f2.write('Valid spikes: ' + str(validSpikeCnt) + '\n')                                                                                       
                f1.close()
                f2.close()                                                            
            # close socket & generating exit and queue it
            Sock.close()
            sys.exit(0)
        # The client sends data (>4) or a "NODATA" message when timeout occurs (==4)
        elif dataLen >= 4:
            if verbose:
                getTime2 = time.time()
            timeoutFlag = 0
            if dataLen == 4:
                cdataNp = np.zeros((0, 4))
                timeoutFlag = 1
                if 0:
                    print "No data"                
            else:
                if not isUdp:
                    while dataLen % 32 != 0: # For avoiding errors because of MSS in TCP    
                        data += conn.recv(buf)
                        dataLen = len(data)                      
                dlen = dataLen / 8 # double : 8 bytes         
                drows = dlen / 4   # 4 fields : |data type|ch#|unit#|TS|
                cdata = struct.unpack('d' * dlen, data)
                cdataNp = np.asarray(cdata).reshape(drows, 4) # convert tuple to 2D numpy array
            if timeMeasure:                                                       
                mA[0] = O_RCV  
                mSock.sendto(mA.tostring(), mAddr3)
                #number += 1 
            if isLwc == 1:
                if timeMeasure:
                    #### ack_rcv1 for filtering
                    mA[0] = O_SND  
                    mSock.sendto(mA.tostring(), mAddr1)

                if syncSpkFilter > 0:
                    cdataNp = nrn_py_filterSyncSpk(cdataNp)
                if unsortedSpkFilter == 1:
                    cdataNp = nrn_py_filterUnsortedSpk(cdataNp);

            if timeMeasure:                                                       
                #### ack_rcv1 for filtering
                mA[0] = O_RCV
                mSock.sendto(mA.tostring(), mAddr1)
            
            drows, col = cdataNp.shape            
            if timeMeasure:       
                #mA[0] = O_FLT
                #mSock.sendto(mA.tostring(), mAddr)  
                #### ack_rcv2 for buffering                           
                mA[0] = O_SND  
                mSock.sendto(mA.tostring(), mAddr2)
            # "NODATA" message
            if drows == 0 and timeoutFlag == 1:
                if verbose: 
                    print "Client sends a NODATA message due to timeout!"
                if verbose:
                    getTime2 = time.time()
                # Generating timeout queue item (Itimeout)
                spk[2] = lastEndTS # last end timestamp of previous data
                spk[SPKSZ - 2] =  lastEndTS + TIMEOUT # it should be second.last timestamp of previous data + TIMEOUT
                spk[SPKSZ - 1] = 0 # number of spikes
                spk[SPKSZ] = SN # serial number from 1
                lastEndTS += TIMEOUT
                SN += 1 
                if verbose:
                    f3.write("loopTime: " + str(time.time()- a) + "\t")
                    qtime = time.time()
                feedQueue(spk, verbose) #queue.put(spk)
                if verbose:
                    f3.write("qTime: " + str(time.time()- qtime) + "\n")                
                    a = time.time()  
                    #f1.write("========\n") 
            else:
                if verbose and drows > 0:#verbose:
                    f_handle = file('spk_rcv.txt', 'a')
                    np.savetxt(f_handle, cdataNp, fmt= '%4d %4d %4d %10.4f')
                    f_handle.close()
                    #f3.write("gTime2: " + str(time.time() - getTime2) + "\n")   
                    #a = time.time() # for measureing loop time               
                for j in range(drows):
                    if verbose:  
                        totalSpikeCnt += 1
                        #print int(cdataNp[j][1]), int(cdataNp[j][2]), cdata[j][3]                                                                
                        #f1.write(str(int(cdataNp[j][0])) + '\t' + str(int(cdataNp[j][1])) + '\t' +str(int(cdataNp[j][2])) + '\t' +str('{:g}'.format(cdataNp[j][3])) + '\n')                                
                        f1.write(str(int(cdataNp[j][1])) + '\t' +str(int(cdataNp[j][2])) + '\t' +str('{:g}'.format(cdataNp[j][3])) + '\n')                                
                    if cdataNp[j][0] == 1: # neuron types               
                        channelID = int(cdataNp[j][1])
                        unitID = int(cdataNp[j][2])
                        timeStamp = cdataNp[j][3]  # (second)
                        if CH_START <= channelID and channelID <= CH_END:   
                            if UNIT_START <= unitID and unitID <= UNIT_END:
                                spk[dataHave * 3] = channelID
                                spk[dataHave * 3 + 1] = unitID
                                spk[dataHave * 3 + 2] = timeStamp
                                dataHave += 1
                                if verbose:
                                    validSpikeCnt += 1
                                    #print "ChID:", spk[0], "UnitID:", spk[1], "Time:", spk[2]
                                    f2.write(str(int(cdataNp[j][1])) + '\t' +str(int(cdataNp[j][2])) + '\t' +str('{:g}'.format(cdataNp[j][3])) + '\n') #'\t' + str(dataHave) + '\t' + str(j) + '\t' + str(drows -1) + '\n')
                                    f3.write(str(int(cdataNp[j][1])) + '\t' +str(int(cdataNp[j][2])) + '\t' +str('{:g}'.format(cdataNp[j][3])) + '\n') #'\t' + str(dataHave) + '\t' + str(j) + '\t' + str(drows -1) + '\n') 
                    if dataHave == SPKNUM or j == drows - 1:              
                        spk[SPKSZ - 1] = dataHave
                        lastEndTS = spk[(dataHave - 1) * 3 + 2]
                        spk[SPKSZ] = SN # serial number from 1
                        SN += 1      
                        if verbose:
                            f3.write("loopTime: " + str(time.time()- a) + "\t")
                            qtime = time.time()

                        if timeMeasure:
                            #### ack_rcv2 for buffering
                            mA[0] = O_RCV
                            mSock.sendto(mA.tostring(), mAddr2)
                            #### ack_rcv2 for buffering
                            mA[0] = O_SND  
                            mSock.sendto(mA.tostring(), mAddr2)
                            #mA[0] = O_END 
                            #mSock.sendto(mA.tostring(), mAddr)                                
                            
                            timer = time.time() 
 
                        feedQueue(spk, verbose) #queue.put(spk)
                        dataHave = 0 

                        if timeMeasure: # timing measure
                            totalMUA +=1             
                            if totalMUA <= iteration:
                                qTimeList.append(time.time() - timer)
                            if totalMUA == iteration + 1:
                                if not os.path.exists(dir):
                                    os.mkdir(dir)
                                fname = dir + "/NslocPushTimeFile"
                                f1 = open(fname, "w+")
                                for item in qTimeList:
                                    f1.write("%s\n" % item)
                                f1.close()  
                                print "Nsloc push"
                            btime = time.time()  
                        if verbose:
                            f3.write("qTime: " + str(time.time()- qtime) + "\n")                
                            a = time.time()  
                            #f1.write("========\n")                           
                            

# For benchmark of no communication case with DP or NSLOC model
def serverNoComm(dir):
    # MUA per channel in a binWnd: [spikes in ch0, spikes in ch1, ..., spikes in ch96, timeInterval]
    print "[serverNoComm is running...]" 
    try:
        if isDp == 1: # inputs through DP cells 
            mua = [0] * (CH_END + 1)
            fname = dir + "/StoredMua.tsv"
            fd = open(fname, 'r')
            for ii in range(1000): # 1000 binned data sets for 100 s
                line = fd.readline()
                binnedMUA = line.split()
                mua[CH_END] = int(binnedMUA[0])/binWnd
                for i in range(CH_END): # index: 0 ~ 96
                    mua[i] = int(binnedMUA[i+1])
                feedQueue(mua, verbose)
                time.sleep(0.1) # emulating 100 ms delay
                #print "%s" % (line)
        else: # inputs through NSLOC units 
            # Monkey spike: [Channel ID, Unit ID, timestamp]
            spk = [0] * (SPKSZ + 1) # = 3 * SPKNUM + 1 + Serial Number 
            dataHave = 0
            SN = 1
            fname = dir + "/spikePMd-6sec.tsv"
            #fname = dir + "/4.tsv"
            fd = open(fname, 'r')
            for locals in fd:
                localts = locals.split()
                if localts[0] == '1': # spikes
                    channelID = int(localts[1])
                    unitID = int(localts[2])
                    timeStamp = float(localts[3])  # (second)
                    #if unsortedSpkFilter and unitID == 0: # filter unsorted spikes
                    #    continue
                    #else:
                    if True:
                        if CH_START <= channelID and channelID <= CH_END:   
                            if UNIT_START <= unitID and unitID <= UNIT_END:
                                spk[dataHave * 3] = channelID
                                spk[dataHave * 3 + 1] = unitID
                                spk[dataHave * 3 + 2] = timeStamp
                                dataHave += 1
                        if dataHave == SPKNUM:              
                            spk[SPKSZ - 1] = dataHave
                            spk[SPKSZ] = SN # serial number from 1
                            SN += 1      
                            feedQueue(spk, verbose) #queue.put(spk)
                            dataHave = 0 
            if dataHave > 0:
                spk[SPKSZ - 1] = dataHave
                spk[SPKSZ] = SN # serial number from 1
                feedQueue(spk, verbose) #queue.put(spk)
                dataHave = 0 
    except:
        print "[serverNoComm] exception occurs:", sys.exc_info()[0]
    finally:
        print "[ServerNoComm is terminated!!!]"
        fd.close()
        sys.exit(0)


class Manager:
    def __init__(self, dir="data"):
        self.workers = []
        self.dir = dir

    def start(self):
        if localFileRead == 0: # spikes delivered through network
            if isDp == 1: # DP
                if isLwc == 0: # Hwc mode
                    self.workers.append(Process(target=nrn_py_interfaceDpHwc, args = (self.dir, ) ))
                else:          # Lwc mode
                    self.workers.append(Process(target=nrn_py_interfaceDpLwc, args = (self.dir, ) ))
            else:# NSLOC (Hwc + Lwc)
                self.workers.append(Process(target=nrn_py_interfaceNsloc, args = (self.dir, )))
        else: # localFileRead == 1, queue test. offline mode, spikes or MUA from a file
            self.workers.append(Process(target=serverNoComm, args = (self.dir, )))

        for w in self.workers:
            w.start()  
        

    def stop(self):
        for w in self.workers:
            w.terminate()     
        print "[Server process is terminated!!!]"
