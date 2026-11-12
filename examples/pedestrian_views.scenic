# The program P from scenic-dmp/example.md, with its views defined in the program.
# A view is a param named view_<name>; the app sets its values or bins (or detects them).
from math import isclose
from scenic.core.distributions import distributionFunction

class Car: pass
class Pedestrian: pass

ego = new Car
d = Options({1: 0.2, 2: 0.5, 3: 0.3})
c = Options({90 deg: 0.5, 0 deg: 0.5})  # crossing or walking along
ped = new Pedestrian ahead of ego by d,
        facing c relative to ego.heading

# distributionFunction delays the call until the scene is sampled, so the body
# sees concrete values and can branch on them.
@distributionFunction
def brake(d, c):
    return "brake" if d <= 2 and isclose(c, 90 deg) else "continue"

param view_brake = brake(d, c)
param view_d = d
