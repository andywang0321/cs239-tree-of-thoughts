Tree of Thoughts paper
Cecilia’s questions:

What is the main contribution of the ToT paper

“Thought” as a unit of reasoning – how does this choice of unit affect performance

Sample vs Propose: which one is more important? Which for what situation? Any tradeoffs?

Value vs Vote: tradeoffs?

Branch pruning: how do you know if you’ve prematurely pruned a “good” branch? Is there a way to “undo”?

BFS vs DFS: Is this task-specific or is there value in comparing BFS vs DFS for each task? Which is better for which type of task?

“Sure”/“Maybe”/“Impossible”: is this too granular? Would a confidence score be better?

1x “Sure” + 2x “Impossible”, vs 2x “Maybe”: which one is more certain?

Creative writing: would going 1 or 2 steps further than one thought step be better for creative tasks? Under what circumstances would adding / removing additional intermediate thought steps be beneficial? How to design good intermediate steps?

Creative writing evaluator: What exactly are we evaluating? Better writing? More creativity? What prior biases are present for the evaluator model?

Andy’s Questions:

Evaluate current status: How to define a good evaluation metric?

Game of 24, Creative writing, Crosswords: To what extent are these new problems engineered specifically towards the ToT's advantage?

- Game of 24 requires keeping a lot of candidate solutions in mind
- Creative writing requires exploring multiple possible plot twists
- Crosswords also require conditioning on different possible solutions for other blanks

Given this construction of problem solving, is a probabilistic model like an LM necessarily the best way to conduct the search through this problem space?

Is the "characteristically human" approach to problem-solving necessarily the best approach? 
What limitations/advantages do humans/agents have that facilitate different approaches to problem solving?

How to decompose a reasoning trace into a thought? Is this an introduction of human prior? Would this be considered privileged knowledge? Are there problems where it is inherently difficult to design a clear unit of "thought"?

Sample vs Propose:  “works better when the thought space is rich”: But are there theoretical guarantees? What if multiple paragraphs are actually the same ideas but worded differently?
How does changing the LM's temperature affect the effectiveness of sampling?

Using the LM to reason about states: Today, could this be replaced by something like JEV?

Voting, pruning, and BFS: Would this be too greedy? How to balance exploration and exploitation? Can we combine `value` and `vote` (e.g. value for first half, vote for second)?

IO vs CoT vs CoT-SC vs ToT: But if ToT is the generalized case of its competitors (and uses combinatorially more tokens and compute), does this paper still make a fair comparison? Is there something clever here, or are we just finding ways to consume more tokens?

