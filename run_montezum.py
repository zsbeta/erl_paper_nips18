import numpy as np, os, time, sys, random
from core import mod_neuro_evo as utils_ne
from core import mod_utils as utils
import gym, torch
from core import replay_memory
from core import ddpg_cnn as ddpg
import argparse
from skimage.color import rgb2gray
from skimage.transform import resize

"""
def add_env_params(parser):
    parser.add_argument('--env', help='environment ID', default='MontezumaRevengeNoFrameskip-v4')
    #parser.add_argument('--seed', help='RNG seed', type=int, default=0)
    parser.add_argument('--max_episode_steps', type=int, default=4500)

    parser.add_argument('--num-timesteps', type=int, default=int(1e12))
"""
#pre process the state to minimise the size of the state
def pre_process(image):
    image = np.array(image)
    image = resize(image, (84, 84, 3))
    # image = rgb2gray(image)
    return image


render = False
parser = argparse.ArgumentParser()
parser.add_argument('-env',
help='Environment Choices: (HalfCheetah-v2) (Ant-v2) (Reacher-v2) (Walker2d-v2) (Swimmer-v2) (Hopper-v2)',default='MontezumaRevengeNoFrameskip-v4') #required=True)
env_tag = vars(parser.parse_args())['env']
GPU = True
print("is cuda available: ", torch.cuda.is_available())
device_idx = 0
if GPU:
    device = torch.device("cuda:" + str(device_idx) if torch.cuda.is_available() else "cpu")
else:
    device = torch.device("cpu")
print(device)

class Parameters:
    def __init__(self):

        #Number of Frames to Run
        if env_tag == 'Hopper-v2': self.num_frames = 4000000
        elif env_tag == 'Ant-v2': self.num_frames = 6000000
        elif env_tag == 'Walker2d-v2': self.num_frames = 8000000
        else: self.num_frames = 3000000
        print("-------current_env", env_tag)
        #USE CUDA
        self.is_cuda = True; self.is_memory_cuda = True
        print("--------cuda available:", self.is_cuda)
        #Sunchronization Period
        if env_tag == 'Hopper-v2' or env_tag == 'Ant-v2': self.synch_period = 1
        else: self.synch_period = 10

        #DDPG params
        self.use_ln = True
        self.gamma = 0.99; self.tau = 0.001
        self.seed = 7
        self.batch_size = 4
        self.buffer_size = 1000
        self.frac_frames_train = 1.0
        self.use_done_mask = True

        ###### NeuroEvolution Params ########
        #Num of trials
        if env_tag == 'Hopper-v2' or env_tag == 'Reacher-v2': self.num_evals = 5
        elif env_tag == 'Walker2d-v2': self.num_evals = 3
        else: self.num_evals = 1

        #Elitism Rate
        if env_tag == 'Hopper-v2' or env_tag == 'Ant-v2': self.elite_fraction = 0.3
        elif env_tag == 'Reacher-v2' or env_tag == 'Walker2d-v2': self.elite_fraction = 0.2
        else: self.elite_fraction = 0.1


        self.pop_size = 10
        self.crossover_prob = 0.6
        self.mutation_prob = 0.9

        #Save Results
        self.state_dim = None; self.action_dim = None #Simply instantiate them here, will be initialized later
        self.save_foldername = 'R_ERL/'
        if not os.path.exists(self.save_foldername): os.makedirs(self.save_foldername)

class Agent:
    def __init__(self, args, env):
        self.args = args; self.env = env
        self.evolver = utils_ne.SSNE(self.args)

        #Init population
        self.pop = []# each population is an actor
        for _ in range(args.pop_size):
            self.pop.append(ddpg.Actor(args))

        #Turn off gradients and put in eval mode
        for actor in self.pop: actor.eval()

        #Init RL Agent
        self.rl_agent = ddpg.DDPG(args)
        self.replay_buffer = replay_memory.ReplayMemory(args.buffer_size)
        self.ounoise = ddpg.OUNoise(args.action_dim)

        #Trackers
        self.num_games = 0; self.num_frames = 0; self.gen_frames = None

    def add_experience(self, state, action, next_state, reward, done):
        reward = utils.to_tensor(np.array([reward])).unsqueeze(0)
        reward = reward.to(device=device)
        if self.args.use_done_mask:
            done = utils.to_tensor(np.array([done]).astype('uint8')).unsqueeze(0)
            done = done.to(device=device)

        #print("--------action ", action, "state: ", state.shape, " next_state", next_state.shape)
        #input()
        self.replay_buffer.push(state, action, next_state, reward, done)

    def evaluate(self, net, is_render, is_action_noise=False, store_transition=True):
        total_reward = 0.0

        state = self.env.reset()
        state = utils.to_tensor(state)
        state = state.to(device=device)

        done = False

        while not done:
            if store_transition: self.num_frames += 1; self.gen_frames += 1
            if render and is_render: self.env.render()
            state = pre_process(state.squeeze(0).cpu())
            state = utils.to_tensor(state).unsqueeze(0)
            state = state.to(device=device)
            #
            # print("input_size", input_model.size())
            # input()
            action = net.forward(state)#.unsqueeze(0)
            action.requires_grad = False #insert it into the replay buffer without gradient
            #action.clamp(-1,1) # already int, no need of clamp it
            #action = utils.to_numpy(action.cpu())
            #if is_action_noise: action += self.ounoise.noise() # add more randomless, exploration

            next_state, reward, done, info = self.env.step(action.cpu())#.flatten())  #Simulate one step in environment

            next_state = pre_process(next_state)#memory efficiency
            next_state = utils.to_tensor(next_state).unsqueeze(0)
            next_state = next_state.to(device=device)
            total_reward += reward
            if store_transition: self.add_experience(state, action, next_state, reward, done)
            state = next_state
        if store_transition: self.num_games += 1

        return total_reward #return the total rewarard

    def rl_to_evo(self, rl_net, evo_net):
        for target_param, param in zip(evo_net.parameters(), rl_net.parameters()):
            target_param.data.copy_(param.data)

    def train(self):
        self.gen_frames = 0
        ##****Fitness funtion is the total reward*****
        ####################### EVOLUTION #####################
        all_fitness = []
        #Evaluate genomes/individuals
        for net in self.pop:
            net = net.to(device =device)
            fitness = 0.0
            for eval in range(self.args.num_evals): fitness += self.evaluate(net, is_render=False, is_action_noise=False)
            all_fitness.append(fitness/self.args.num_evals)

        best_train_fitness = max(all_fitness)
        worst_index = all_fitness.index(min(all_fitness))

        #Validation test
        champ_index = all_fitness.index(max(all_fitness))
        test_score = 0.0
        for eval in range(5): test_score += self.evaluate(self.pop[champ_index], is_render=True, is_action_noise=False, store_transition=False)/5.0

        #NeuroEvolution's probabilistic selection and recombination step
        elite_index = self.evolver.epoch(self.pop, all_fitness)


        ####################### DDPG #########################
        #DDPG Experience Collection
        self.evaluate(self.rl_agent.actor, is_render=False, is_action_noise=True) #Train

        #DDPG learning step
        if len(self.replay_buffer) > self.args.batch_size * 5:

            for _ in range(int(self.gen_frames*self.args.frac_frames_train)):
                transitions = self.replay_buffer.sample(self.args.batch_size)
                batch = replay_memory.Transition(*zip(*transitions))

                self.rl_agent.update_parameters(batch)
                # print("......after update: ")
                # input()
            #Synch RL Agent to NE
            if self.num_games % self.args.synch_period == 0:
                self.rl_to_evo(self.rl_agent.actor, self.pop[worst_index])
                self.evolver.rl_policy = worst_index
                print('Synch from RL --> Nevo')

        return best_train_fitness, test_score, elite_index

if __name__ == "__main__":
    parameters = Parameters()  # Create the Parameters class
    tracker = utils.Tracker(parameters, ['erl'], '_score.csv')  # Initiate tracker
    frame_tracker = utils.Tracker(parameters, ['frame_erl'], '_score.csv')  # Initiate tracker
    time_tracker = utils.Tracker(parameters, ['time_erl'], '_score.csv')

    #Create Env action_space /observation_space


    env =gym.make(env_tag) #utils.NormalizedActions(gym.make(env_tag))
    ####Do i need to normalise the action space for montezuma?


    if env.action_space.__class__.__name__ == "Discrete":
        parameters.action_dim = env.action_space.n #discreat action(montezuma)
        #self.action_dim_mode = "Discrete"
    elif envaction_space.__class__.__name__ == "Box":
        parameters.action_dim = env.action_space.shape[0] # continuous action (robotics)
        #self.action_dim_mode = "Box"
    else:
        raise NotImplementedError

    if env.observation_space.__class__.__name__ == "Discrete":
        parameters.state_dim = 1#self.args.observation_space.n
        raise NotImplementedError
    elif env.observation_space.__class__.__name__ == "Box":
        parameters.state_dim = env.observation_space.shape[-1]

    else:
        raise NotImplementedError



    #parameters.action_space = env.action_space#.n# for continuous space: .shape[0]
    #parameters.observation_space = env.observation_space#.shape#for robotic only one dim: [0]


    #Seed
    env.seed(parameters.seed);
    torch.manual_seed(parameters.seed); np.random.seed(parameters.seed); random.seed(parameters.seed)

    #Create Agent
    agent = Agent(parameters, env)
    print('Running', env_tag, ' State_dim:', parameters.state_dim, ' Action_dim:', parameters.action_dim)

    next_save = 100; time_start = time.time()
    while agent.num_frames <= parameters.num_frames:
        best_train_fitness, erl_score, elite_index = agent.train()
        print('#Games:', agent.num_games, '#Frames:', agent.num_frames, ' Epoch_Max:', '%.2f'%best_train_fitness if best_train_fitness != None else None, ' Test_Score:','%.2f'%erl_score if erl_score != None else None, ' Avg:','%.2f'%tracker.all_tracker[0][1], 'ENV '+env_tag)
        print('RL Selection Rate: Elite/Selected/Discarded', '%.2f'%(agent.evolver.selection_stats['elite']/agent.evolver.selection_stats['total']),
                                                             '%.2f' % (agent.evolver.selection_stats['selected'] / agent.evolver.selection_stats['total']),
                                                              '%.2f' % (agent.evolver.selection_stats['discarded'] / agent.evolver.selection_stats['total']))
        print()
        tracker.update([erl_score], agent.num_games)
        frame_tracker.update([erl_score], agent.num_frames)
        time_tracker.update([erl_score], time.time()-time_start)

        #Save Policy
        if agent.num_games > next_save:
            next_save += 100
            if elite_index != None: torch.save(agent.pop[elite_index].state_dict(), parameters.save_foldername + 'evo_net')
            print("Progress Saved")
