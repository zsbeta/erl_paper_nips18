# erl_paper_nips18
Code accompanying the paper "Evolution-Guided Policy Gradients in Reinforcement Learning" accepted at NIPS 2018

###### Dependencies #######
Python 3.5.6 \
Pytorch 0.3.1.post3 \
Numpy 1.15.2 \
Fastrand from https://github.com/lemire/fastrand \
Gym 0.10.5 \
Mujoco-py v1.50.1.59
###### Activate the virtual environment of python3 #######
python3 -m venv ./venv 

source venv/bin/activate
###### Install Dependencies #######

pip install -r requirements.txt

#### To Run #### 
python run_erl.py -env $ENV_NAME$ 

#### ENVS TESTED #### 
'Hopper-v2' \
'HalfCheetah-v2' \
'Swimmer-v2' \
'Ant-v2' \
'Walker2d-v2' \
'Reacher-v2'
# EA_RL
