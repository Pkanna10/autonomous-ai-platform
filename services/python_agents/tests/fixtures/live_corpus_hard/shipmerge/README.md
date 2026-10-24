# shipmerge

Merges the shipment lines of several warehouses into one view: the distinct
stock-keeping units shipped, in the order they first appear, and the arrival
rank of each order among all orders.

```
python -m shipmerge.main
```

The shipments are generated deterministically, so the output is the same on
every run.
