# MIT License
#
# Copyright (c) 2018-2019 Tskit Developers
# Copyright (C) 2017 University of Oxford
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
Test various functions using messy tables output by a forwards-time simulator.
"""
import itertools
import random
import unittest

import msprime
import numpy as np
import numpy.testing as nt

import tests as tests
import tests.tsutil as tsutil
import tskit


class WrightFisherSimulator:
    """
    SIMPLE simulation of a bisexual, haploid Wright-Fisher population of size N
    for ngens generations, in which each individual survives with probability
    survival and only those who die are replaced.  If num_loci is None,
    the chromosome is 1.0 Morgans long, and the mutation rate is in units of
    mutations/Morgan/generation. If num_loci not None, a discrete recombination
    model is used where breakpoints are chosen uniformly from 1 to num_loci - 1.
    """

    def __init__(
        self,
        N,
        survival=0.0,
        seed=None,
        deep_history=True,
        debug=False,
        initial_generation_samples=False,
        num_loci=None,
    ):
        self.N = N
        self.num_loci = num_loci
        self.survival = survival
        self.deep_history = deep_history
        self.debug = debug
        self.initial_generation_samples = initial_generation_samples
        self.seed = seed
        self.rng = random.Random(seed)

    def random_breakpoint(self):
        if self.num_loci is None:
            return min(1.0, max(0.0, 2 * self.rng.random() - 0.5))
        else:
            return self.rng.randint(1, self.num_loci - 1)

    def run(self, ngens):
        L = 1
        if self.num_loci is not None:
            L = self.num_loci
        tables = tskit.TableCollection(sequence_length=L)
        tables.populations.add_row()
        if self.deep_history:
            # initial population
            init_ts = msprime.simulate(
                self.N, recombination_rate=1.0, length=L, random_seed=self.seed
            )
            init_tables = init_ts.dump_tables()
            flags = init_tables.nodes.flags
            if not self.initial_generation_samples:
                flags = np.zeros_like(init_tables.nodes.flags)
            tables.nodes.set_columns(time=init_tables.nodes.time + ngens, flags=flags)
            tables.edges.set_columns(
                left=init_tables.edges.left,
                right=init_tables.edges.right,
                parent=init_tables.edges.parent,
                child=init_tables.edges.child,
            )
        else:
            flags = 0
            if self.initial_generation_samples:
                flags = tskit.NODE_IS_SAMPLE
            for _ in range(self.N):
                tables.nodes.add_row(flags=flags, time=ngens, population=0)

        pop = list(range(self.N))
        for t in range(ngens - 1, -1, -1):
            if self.debug:
                print("t:", t)
                print("pop:", pop)

            dead = [self.rng.random() > self.survival for k in pop]
            # sample these first so that all parents are from the previous gen
            new_parents = [
                (self.rng.choice(pop), self.rng.choice(pop)) for k in range(sum(dead))
            ]
            k = 0
            if self.debug:
                print("Replacing", sum(dead), "individuals.")
            for j in range(self.N):
                if dead[j]:
                    # this is: offspring ID, lparent, rparent, breakpoint
                    offspring = len(tables.nodes)
                    tables.nodes.add_row(time=t, population=0)
                    lparent, rparent = new_parents[k]
                    k += 1
                    bp = self.random_breakpoint()
                    if self.debug:
                        print("--->", offspring, lparent, rparent, bp)
                    pop[j] = offspring
                    if bp > 0.0:
                        tables.edges.add_row(
                            left=0.0, right=bp, parent=lparent, child=offspring
                        )
                    if bp < L:
                        tables.edges.add_row(
                            left=bp, right=L, parent=rparent, child=offspring
                        )

        if self.debug:
            print("Done! Final pop:")
            print(pop)
        flags = tables.nodes.flags
        flags[pop] = tskit.NODE_IS_SAMPLE
        tables.nodes.set_columns(
            flags=flags, time=tables.nodes.time, population=tables.nodes.population
        )
        return tables


def wf_sim(
    N,
    ngens,
    survival=0.0,
    deep_history=True,
    debug=False,
    seed=None,
    initial_generation_samples=False,
    num_loci=None,
):
    sim = WrightFisherSimulator(
        N,
        survival=survival,
        deep_history=deep_history,
        debug=debug,
        seed=seed,
        initial_generation_samples=initial_generation_samples,
        num_loci=num_loci,
    )
    return sim.run(ngens)


class TestSimulation(unittest.TestCase):
    """
    Tests that the simulations produce the output we expect.
    """

    random_seed = 5678

    def test_non_overlapping_generations(self):
        tables = wf_sim(N=10, ngens=10, survival=0.0, seed=self.random_seed)
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertEqual(tables.sites.num_rows, 0)
        self.assertEqual(tables.mutations.num_rows, 0)
        self.assertEqual(tables.migrations.num_rows, 0)
        tables.sort()
        tables.simplify()
        ts = tables.tree_sequence()
        # All trees should have exactly one root and all internal nodes should
        # have arity > 1
        for tree in ts.trees():
            self.assertEqual(tree.num_roots, 1)
            leaves = set(tree.leaves(tree.root))
            self.assertEqual(leaves, set(ts.samples()))
            for u in tree.nodes():
                if tree.is_internal(u):
                    self.assertGreater(len(tree.children(u)), 1)

    def test_overlapping_generations(self):
        tables = wf_sim(N=30, ngens=10, survival=0.85, seed=self.random_seed)
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertEqual(tables.sites.num_rows, 0)
        self.assertEqual(tables.mutations.num_rows, 0)
        self.assertEqual(tables.migrations.num_rows, 0)
        tables.sort()
        tables.simplify()
        ts = tables.tree_sequence()
        for tree in ts.trees():
            self.assertEqual(tree.num_roots, 1)

    def test_one_generation_no_deep_history(self):
        N = 20
        tables = wf_sim(N=N, ngens=1, deep_history=False, seed=self.random_seed)
        self.assertEqual(tables.nodes.num_rows, 2 * N)
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertEqual(tables.sites.num_rows, 0)
        self.assertEqual(tables.mutations.num_rows, 0)
        self.assertEqual(tables.migrations.num_rows, 0)
        tables.sort()
        tables.simplify()
        ts = tables.tree_sequence()
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        ts = tables.tree_sequence()
        for tree in ts.trees():
            all_samples = set()
            for root in tree.roots:
                root_samples = set(tree.samples(root))
                self.assertEqual(len(root_samples & all_samples), 0)
                all_samples |= root_samples
            self.assertEqual(all_samples, set(ts.samples()))

    def test_many_generations_no_deep_history(self):
        N = 10
        ngens = 100
        tables = wf_sim(N=N, ngens=ngens, deep_history=False, seed=self.random_seed)
        self.assertEqual(tables.nodes.num_rows, N * (ngens + 1))
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertEqual(tables.sites.num_rows, 0)
        self.assertEqual(tables.mutations.num_rows, 0)
        self.assertEqual(tables.migrations.num_rows, 0)
        tables.sort()
        tables.simplify()
        ts = tables.tree_sequence()
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        ts = tables.tree_sequence()
        # We are assuming that everything has coalesced and we have single-root trees
        for tree in ts.trees():
            self.assertEqual(tree.num_roots, 1)

    def test_with_mutations(self):
        N = 10
        ngens = 100
        tables = wf_sim(N=N, ngens=ngens, deep_history=False, seed=self.random_seed)
        tables.sort()
        ts = tables.tree_sequence()
        ts = tsutil.jukes_cantor(ts, 10, 0.1, seed=self.random_seed)
        tables = ts.tables
        self.assertGreater(tables.sites.num_rows, 0)
        self.assertGreater(tables.mutations.num_rows, 0)
        samples = np.where(tables.nodes.flags == tskit.NODE_IS_SAMPLE)[0].astype(
            np.int32
        )
        tables.sort()
        tables.simplify(samples)
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertGreater(tables.sites.num_rows, 0)
        self.assertGreater(tables.mutations.num_rows, 0)
        ts = tables.tree_sequence()
        self.assertEqual(ts.sample_size, N)
        for hap in ts.haplotypes():
            self.assertEqual(len(hap), ts.num_sites)

    def test_with_recurrent_mutations(self):
        # actually with only ONE site, at 0.0
        N = 10
        ngens = 100
        tables = wf_sim(N=N, ngens=ngens, deep_history=False, seed=self.random_seed)
        tables.sort()
        ts = tables.tree_sequence()
        ts = tsutil.jukes_cantor(ts, 1, 10, seed=self.random_seed)
        tables = ts.tables
        self.assertEqual(tables.sites.num_rows, 1)
        self.assertGreater(tables.mutations.num_rows, 0)
        # before simplify
        for h in ts.haplotypes():
            self.assertEqual(len(h), 1)
        # after simplify
        tables.sort()
        tables.simplify()
        self.assertGreater(tables.nodes.num_rows, 0)
        self.assertGreater(tables.edges.num_rows, 0)
        self.assertEqual(tables.sites.num_rows, 1)
        self.assertGreater(tables.mutations.num_rows, 0)
        ts = tables.tree_sequence()
        self.assertEqual(ts.sample_size, N)
        for hap in ts.haplotypes():
            self.assertEqual(len(hap), ts.num_sites)


class TestIncrementalBuild(unittest.TestCase):
    """
    Tests for incrementally building a tree sequence from forward time
    simulations.
    """


class TestSimplify(unittest.TestCase):
    """
    Tests for simplify on cases generated by the Wright-Fisher simulator.
    """

    def assertArrayEqual(self, x, y):
        nt.assert_equal(x, y)

    def assertTreeSequencesEqual(self, ts1, ts2):
        self.assertEqual(list(ts1.samples()), list(ts2.samples()))
        self.assertEqual(ts1.sequence_length, ts2.sequence_length)
        ts1_tables = ts1.dump_tables()
        ts2_tables = ts2.dump_tables()
        # print("compare")
        # print(ts1_tables.nodes)
        # print(ts2_tables.nodes)
        self.assertEqual(ts1_tables.nodes, ts2_tables.nodes)
        self.assertEqual(ts1_tables.edges, ts2_tables.edges)
        self.assertEqual(ts1_tables.sites, ts2_tables.sites)
        self.assertEqual(ts1_tables.mutations, ts2_tables.mutations)

    def get_wf_sims(self, seed):
        """
        Returns an iterator of example tree sequences produced by the WF simulator.
        """
        for N in [5, 10, 20]:
            for surv in [0.0, 0.5, 0.9]:
                for mut in [0.01, 1.0]:
                    for nloci in [1, 2, 3]:
                        tables = wf_sim(N=N, ngens=N, survival=surv, seed=seed)
                        tables.sort()
                        ts = tables.tree_sequence()
                        ts = tsutil.jukes_cantor(ts, num_sites=nloci, mu=mut, seed=seed)
                        self.verify_simulation(ts, ngens=N)
                        yield ts

    def verify_simulation(self, ts, ngens):
        """
        Verify that in the full set of returned tables there is parentage
        information for every individual, except those initially present.
        """
        tables = ts.dump_tables()
        for u in range(tables.nodes.num_rows):
            if tables.nodes.time[u] <= ngens:
                lefts = []
                rights = []
                k = 0
                for edge in ts.edges():
                    if u == edge.child:
                        lefts.append(edge.left)
                        rights.append(edge.right)
                    k += 1
                lefts.sort()
                rights.sort()
                self.assertEqual(lefts[0], 0.0)
                self.assertEqual(rights[-1], 1.0)
                for k in range(len(lefts) - 1):
                    self.assertEqual(lefts[k + 1], rights[k])

    def verify_simplify(self, ts, new_ts, samples, node_map):
        """
        Check that trees in `ts` match `new_ts` using the specified node_map.
        Modified from `verify_simplify_topology`.  Also check that the `parent`
        and `time` column in the MutationTable is correct.
        """
        # check trees agree at these points
        locs = [random.random() for _ in range(20)]
        locs += random.sample(list(ts.breakpoints())[:-1], min(20, ts.num_trees))
        locs.sort()
        old_trees = ts.trees()
        new_trees = new_ts.trees()
        old_right = -1
        new_right = -1
        for loc in locs:
            while old_right <= loc:
                old_tree = next(old_trees)
                old_left, old_right = old_tree.get_interval()
            assert old_left <= loc < old_right
            while new_right <= loc:
                new_tree = next(new_trees)
                new_left, new_right = new_tree.get_interval()
            assert new_left <= loc < new_right
            # print("comparing trees")
            # print("interval:", old_tree.interval)
            # print(old_tree.draw(format="unicode"))
            # print("interval:", new_tree.interval)
            # print(new_tree.draw(format="unicode"))
            pairs = itertools.islice(itertools.combinations(samples, 2), 500)
            for pair in pairs:
                mapped_pair = [node_map[u] for u in pair]
                mrca1 = old_tree.get_mrca(*pair)
                self.assertNotEqual(mrca1, tskit.NULL)
                mrca2 = new_tree.get_mrca(*mapped_pair)
                self.assertNotEqual(mrca2, tskit.NULL)
                self.assertEqual(node_map[mrca1], mrca2)
        mut_parent = tsutil.compute_mutation_parent(ts=ts)
        self.assertArrayEqual(mut_parent, ts.tables.mutations.parent)

    def verify_haplotypes(self, ts, samples):
        """
        Check that haplotypes are unchanged by simplify.
        """
        sub_ts, node_map = ts.simplify(
            samples, map_nodes=True, filter_zero_mutation_sites=False
        )
        # Sites tables should be equal
        self.assertEqual(ts.tables.sites, sub_ts.tables.sites)
        sub_haplotypes = dict(zip(sub_ts.samples(), sub_ts.haplotypes()))
        all_haplotypes = dict(zip(ts.samples(), ts.haplotypes()))
        mapped_ids = []
        for node_id, h in all_haplotypes.items():
            mapped_node_id = node_map[node_id]
            if mapped_node_id in sub_haplotypes:
                self.assertEqual(h, sub_haplotypes[mapped_node_id])
                mapped_ids.append(mapped_node_id)
        self.assertEqual(sorted(mapped_ids), sorted(sub_ts.samples()))

    def test_simplify(self):
        #  check that simplify(big set) -> simplify(subset) equals simplify(subset)
        seed = 23
        random.seed(seed)
        for ts in self.get_wf_sims(seed=seed):
            s = tests.Simplifier(ts, ts.samples())
            py_full_ts, py_full_map = s.simplify()
            full_ts, full_map = ts.simplify(ts.samples(), map_nodes=True)
            self.assertTrue(all(py_full_map == full_map))
            self.assertTreeSequencesEqual(full_ts, py_full_ts)

            for nsamples in [2, 5, 10]:
                sub_samples = random.sample(
                    list(ts.samples()), min(nsamples, ts.sample_size)
                )
                s = tests.Simplifier(ts, sub_samples)
                py_small_ts, py_small_map = s.simplify()
                small_ts, small_map = ts.simplify(samples=sub_samples, map_nodes=True)
                self.assertTreeSequencesEqual(small_ts, py_small_ts)
                self.verify_simplify(ts, small_ts, sub_samples, small_map)
                self.verify_haplotypes(ts, samples=sub_samples)

    def test_simplify_tables(self):
        seed = 71
        for ts in self.get_wf_sims(seed=seed):
            for nsamples in [2, 5, 10]:
                tables = ts.dump_tables()
                sub_samples = random.sample(
                    list(ts.samples()), min(nsamples, ts.num_samples)
                )
                node_map = tables.simplify(samples=sub_samples)
                small_ts = tables.tree_sequence()
                other_tables = small_ts.dump_tables()
                tables.provenances.clear()
                other_tables.provenances.clear()
                self.assertEqual(tables, other_tables)
                self.verify_simplify(ts, small_ts, sub_samples, node_map)
