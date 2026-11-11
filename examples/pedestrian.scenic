# The program P from scenic-dmp/example.md.
# Stand-in classes so the program runs without a simulator model.
# A driving-domain model would add default requirements that can reject samples and change μ.
class Car: pass
class Pedestrian: pass

ego = new Car
d = Options({1: 0.2, 2: 0.5, 3: 0.3})
c = Options({90 deg: 0.5, 0 deg: 0.5})  # crossing or walking along
ped = new Pedestrian ahead of ego by d,
        facing c relative to ego.heading
