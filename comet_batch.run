#!/bin/sh
#SBATCH -o stdout.%j.%N.txt# Name of stdout output file(%j expands to jobId)
#SBATCH -e stderr.%j.%N.txt# Name of stderr output file(%j expands to jobId)
#SBATCH --partition=compute    # submit to the 'large' queue for jobs > 256 nodes
#SBATCH -J m1ms_evol_islands        # Job name
#SBATCH -t 48:00:00            # Run time (hh:mm:ss) 
#SBATCH --mail-user=salvadordura@gmail.com
#SBATCH --mail-type=end
#SBATCH -A csd403              # Allocation name to charge job against
#SBATCH --nodes=1              # Total number of nodes requested (24 cores/node)
#SBATCH --ntasks-per-node=6    # Total (?) number of mpi tasks requested; see also below: --npernode; CIPRES_THREADSPP; CIPRES_NP
#SBATCH --res=salvadord_371
#SBATCH --switches=1
#SBATCH --export=ALL
##SBATCH --qos=nsg

module purge
module load intel
export MODULEPATH=/share/apps/compute/modulefiles/mpi:$MODULEPATH
module load openmpi_ib/1.8.4npmi
module load python
module load gsl
module load scipy
module load gnu
module load mkl

export PATH=~nsguser/applications/neuron7.4/installdir/x86_64/bin:~nsguser/.local/bin:$PATH
export LD_LIBRARY_PATH=~nsguser/applications/neuron7.4/installdir/x86_64/lib:$LD_LIBRARY_PATH

cd '/home/salvadord/m1ms/sim/'

python evol_islands.py 

