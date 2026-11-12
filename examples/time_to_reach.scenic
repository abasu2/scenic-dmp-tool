# A pedestrian at a random gap ahead of an ego car with a random speed.
# The view in time_to_reach.dmp.json is the time for the ego to reach the pedestrian,
# gap / speed in seconds: a continuous value, so the view sorts it into bins.
# Stand-in classes so the program runs without a simulator model.
class Car: pass
class Pedestrian: pass

gap = Range(5, 40)  # m
ego = new Car with speed Range(5, 15)  # m/s
ped = new Pedestrian ahead of ego by gap
