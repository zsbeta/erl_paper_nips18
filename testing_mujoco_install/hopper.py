import mujoco_py
import gym
env = gym.make('Humanoid-v2')  # or 'Humanoid-v2'

for i_episode in range(20):
    observation = env.reset()
    for t in range(10000):
        env.render()
        print(observation)
        action = env.action_space.sample()
        observation, reward, done, info = env.step(action)
        if done:
            print("Episode finished after {} timesteps".format(t+1))
            break
env.close()
