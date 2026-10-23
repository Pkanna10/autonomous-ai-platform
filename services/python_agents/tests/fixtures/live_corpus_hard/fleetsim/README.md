# fleetsim

A discrete-event simulation of a delivery fleet: jobs appear across a city grid
during the day, a dispatcher assigns each to a vehicle, vehicles drive, load,
deliver and return to their depots for charging, and the run ends with a service
report (waiting times and their percentiles, the share of jobs each customer
tier saw delivered on time, vehicle utilisation and energy).

```
python -m fleetsim.main
```

Modules:

- `feed`: the deterministic city, depots, vehicles and jobs
- `geometry`: points, grid distances and travel times
- `fleet`: vehicles and depots, battery and load state
- `agenda`: the ordered event agenda of the simulation
- `dispatch`: choosing a vehicle for each job
- `simulation`: the event loop
- `metrics`: statistics over the recorded samples
- `service`: per-job service levels
- `report`: the end-of-day report
- `tariffs`: what a day's charging costs
- `timeline`: demand and waits hour by hour
- `checks`: sanity checks on a simulated day
