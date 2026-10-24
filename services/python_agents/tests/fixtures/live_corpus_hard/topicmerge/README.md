# topicmerge

Merges the topic labels that a forum's moderators attached to its posts: prints
every topic once, in the order the topic was first used, with how many posts
carry it, then the posts per board.

```
python -m topicmerge.main
```

The posts are generated deterministically, so the output is the same on every
run.
