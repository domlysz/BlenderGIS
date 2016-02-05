# -*- coding:utf-8 -*-

"""
1Dkmeans.py
Author : domlysz@gmail.com
Date : 2016

This file is part of BlenderGIS

This is a kmeans implementation optimized for 1D data

Original kmeans code :
https://gist.github.com/iandanforth/5862470

1D optimisations are inpired from this talking
http://stats.stackexchange.com/questions/40454/determine-different-clusters-of-1d-data-from-database

Optimizations consists to:
-sort the data and initialize clusters with a quantile classification
-compute distance in 1D instead of euclidean
-optimize only the borders of the clusters instead of test each cluster values


Clustering results are similar to Jenks natural break and ckmeans algorithms.
There are Python implementations of these alg. based on javascript code from simple-statistics library :
https://gist.github.com/llimllib/4974446 (https://gist.github.com/tmcw/4977508)
https://github.com/llimllib/ckmeans (https://github.com/simple-statistics/simple-statistics/blob/master/src/ckmeans.js)

But they are terribly slow, in contrast this script works in a reasonable time. 
"""

import math


class Cluster():
	'''
	A set of values and their centroid
	'''
	
	def __init__(self, values):
		#init cluster values list with initial centroid
		self.values = values
		# Set up the initial centroid
		self.centroid = self.getCentroid()
	
	def updateCentroid(self):
		'''
		Returns the distance between the previous centroid and the new after
		recalculating and storing the new centroid.
		'''
		old_centroid = self.centroid
		self.centroid = self.getCentroid()
		shift = abs(old_centroid - self.centroid)
		return shift
	
	def getCentroid(self):
		'''
		Finds a virtual center point for a group of 1-dimensional values
		Centroid = mean
		'''
		return sum(self.values) / len(self.values)
		


def kmeans1d(data, k, cutoff=0.1):
	'''
	Compute natural breaks of a one dimensionnal list through an optimized kmeans algorithm
	data = input list, must be sorted beforehand
	k = number of expected classes
	cutoff = stop algorithm when centroids shift are under this value
	'''
		
	# Step 1: Create k clusters with quantile classification
	n = len(data)
	q = int(math.ceil(n/k))
	clusters = [Cluster(data[i:q+i]) for i in range(0,n,q)]

	# Loop through the dataset until the clusters stabilize
	loopCounter = 0
	while True:
		clusterCount = len(clusters)		
		# Start counting loops
		loopCounter += 1
		
		# Step 2 : for each cluster...
		for i in range(clusterCount-1):
			c1 = clusters[i] #current cluster
			c2 = clusters[i+1] #next cluster
			
			# Test the distance between the right border of the current cluster and the neightbors centroids
			# Move the values if it's closer to the next cluster's centroid. 
			# Then, test the new right border or stop if no more move is needed.
			while True:
				breakValue = c1.values[-1]#max(c1.values)
				dst1 = abs(breakValue - c1.centroid)
				dst2 = abs(breakValue - c2.centroid)
				if dst1 > dst2:
					v = c1.values.pop()
					c2.values.insert(0, v)
				else:
					break
			
			# Test the distance between the left border of the next cluster and the neightbors centroids
			# Move the values if it's closer to the previous cluster's centroid. 
			# Then, test the new left border or stop if no more move is needed.					
			while True:
				breakValue = c2.values[0]
				dst1 = abs(breakValue - c1.centroid)
				dst2 = abs(breakValue - c2.centroid)
				if dst2 > dst1:
					v = c2.values.pop(0)
					c1.values.append(v)
				else:
					break
			
					
		# Step 3: update centroids and stop main loop if they have stopped moving much
		# Set our biggest_shift to zero for this iteration
		biggest_shift = 0
		# As many times as there are clusters ...
		for i in range(clusterCount):
			# Update cluster centroid according to new affected values
			# it return how far the centroid moved in this iteration
			shift = clusters[i].updateCentroid()
			# Keep track of the largest move from all cluster centroid updates
			biggest_shift = max(biggest_shift, shift)
		# If the centroids have stopped moving much, say we're done!
		if biggest_shift < cutoff:
			print("Converged after %s iterations" % loopCounter)
			break

	return clusters
