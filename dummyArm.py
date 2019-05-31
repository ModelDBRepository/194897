# dummyArm.py -- Python code for interfacing the sim with a virtual arm
# 
# Last update: 07/21/14 (salvadordura@gmail.com)

import matplotlib 
matplotlib.use('TkAgg') # for visualization
from socket import *  
import select	# for socket reading
import struct	# to pack messages for socket comms	
import numpy
from pylab import figure, show, ion, pause


# Initialize and setup the sockets and data format 
def setup():
	sendMsgFormat = "dd"  # messages contain 2 doubles = joint angles of shoulder and elbow 
	receiveMsgFormat = "dd"  # messages contain 2 doubles =  velocities
	receiveMsgSize = struct.calcsize(receiveMsgFormat)
	localHostIP =  "127.0.0.1"#"localhost"#"192.168.1.2"# # set IP for local connection 

	print "Setting up connection..." # setup connection to model
	sockReceive = socket(AF_INET, SOCK_DGRAM) # create sockets
	hostPortReceive = 31000 # set port for receiving packets
	sockReceive.bind(('', hostPortReceive)) # bind to port
	sockReceive.setblocking(1) # Set blocking/non-blocking mode
	print ("Created UDP socket to receive packets from NEURON model; binded to port %d"%hostPortReceive)
		
	sockSend = socket(AF_INET, SOCK_DGRAM) 	# connect to socket for sending packets	
	hostPortSend = 32000 # set port for sending packets
	sockSend.connect((localHostIP, hostPortSend))
	sockSend.setblocking(1) # Set blocking/non-blocking mode
	print ("Created UDP socket to send packets to NEURON model; socket connected to IP %s, port %d" % (localHostIP, hostPortSend))

	return sendMsgFormat, receiveMsgFormat,  sockReceive, sockSend

# Send and receive packets to/from virtual arm
def sendAndReceivePackets(dataSend, sendMsgFormat, receiveMsgFormat,  sockReceive, sockSend):
	dataReceived = [0,0]
	try:
		receiveMsgSize = struct.calcsize(receiveMsgFormat)
		dataReceivedPacked = sockReceive.recv(receiveMsgSize) # read packet from socket	
		if len(dataReceivedPacked) == receiveMsgSize:
			dataReceived = struct.unpack(receiveMsgFormat, dataReceivedPacked)
			print "Received packet from model: (%.2f,%.2f)" % (dataReceived[0],dataReceived[1])
	except:
		print "Error receiving packet"

	inputready, outputready, e = select.select([] ,[sockSend],[], 0.0) 	# check if other side ready to receive
	if len(outputready)>0:
		try: 
			sent = sockSend.send(struct.pack(sendMsgFormat, dataSend[0], dataSend[1])) # send packet
			print "Sent packet to virtual arm: (%.2f, %.2f)" % (dataSend[0], dataSend[1])
		except:
			print "Sending socket ready but error sending packet"
	else:
		print "Sending socket not ready"	
	return dataReceived	  

# Main code for simple virtual arm
duration = 4 # sec
interval = 0.010 # time between packets (sec)
L1 = 1.0 # arm segment 1 length 
L2 = 0.8 # arm segment 2 length
shang = numpy.pi/2 # shoulder angle (rad) 
elang = numpy.pi/2 # elbow angle (rad) 
shvel = 0 # shoulder velocity (rad/s)
elvel = 0 # elbow velocity (rad/s)
friction = 0.1 # friction coefficient

sendMsgFormat, receiveMsgFormat,  sockReceive, sockSend = setup() # setup network comm

ion()
fig = figure() # create figure
ax = fig.add_subplot(111, autoscale_on=False, xlim=(-2, 2), ylim=(-2, 2)) # create subplot
ax.grid()
line, = ax.plot([], [], 'o-', lw=2)

raw_input("Press Enter to continue...")
for i in numpy.arange(0, duration, interval):
	shang = (shang + shvel * interval) % (2*numpy.pi) # update shoulder angle
	elang = (elang + elvel * interval) % (2*numpy.pi)# update elbow angle
	if shang<0: shang = 2*numpy.pi + shang
	if elang<0: elang = 2*numpy.pi + shang
	shpos = [L1*numpy.sin(shang), L1*numpy.cos(shang)] # calculate shoulder x-y pos
	elpos = [L2*numpy.sin(shang+elang) + shpos[0], L2*numpy.cos(shang+elang) + shpos[1]] # calculate elbow x-y pos

	dataSend = [shang, elang] # set data to send
	dataReceived = sendAndReceivePackets(dataSend, sendMsgFormat, receiveMsgFormat,  sockReceive, sockSend) # send and receive data
	shvel = shvel+dataReceived[0] - (friction * shvel)# update velocities based on incoming commands (accelerations) and friction
	elvel = elvel+dataReceived[1] - (friction * elvel)

	line.set_data([0, shpos[0], elpos[0]], [0, shpos[1], elpos[1]]) # update line in figure
	ax.set_title('Time = %.1f ms, shoulder: pos=%.2f rad, vel=%.2f, acc=%.2f ; elbow: pos = %.2f rad, vel = %.2f, acc=%.2f' % (float(i)*1000, shang, shvel, dataReceived[0] - (friction * shvel), elang, elvel, dataReceived[1] - (friction * elvel) ), fontsize=10)
	show()
	pause(0.0001) # pause so that the figure refreshes at every time step








