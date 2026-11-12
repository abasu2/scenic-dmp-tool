# The program P from scenic-dmp/example-rare.md: pedestrian.scenic with a rare gap d = 0.5.
# Under the view f (collide / brake / continue), collide has probability 0.001, so
# n = 200 samples usually miss it. pedestrian_rare.dmp.json is a workspace with f defined.
# Stand-in classes so the program runs without a simulator model.
class Car: pass
class Pedestrian: pass

ego = new Car
d = Options({0.5: 0.002, 1: 0.198, 2: 0.5, 3: 0.3})
c = Options({90 deg: 0.5, 0 deg: 0.5})  # crossing or walking along
ped = new Pedestrian ahead of ego by d,
        facing c relative to ego.heading
