# -*- coding:utf-8 -*-
"""
kmeans1D.py
Author : domlysz@gmail.com
Date : 2016

This file is part of BlenderGIS.
This is a kmeans implementation optimized for 1D data.

Original kmeans code :
https://gist.github.com/iandanforth/5862470

1D optimisations are inspired from this talking :
http://stats.stackexchange.com/questions/40454/determine-different-clusters-of-1d-data-from-database

Optimizations consists to :
-sort the data and initialize clusters with a quantile classification
-compute distance in 1D instead of euclidean
-optimize only the borders of the clusters instead of test each cluster values

Clustering results are similar to Jenks natural break and ckmeans algorithms.
There are Python implementations of these alg. based on javascript code from simple-statistics library :
* Jenks : https://gist.github.com/llimllib/4974446 (https://gist.github.com/tmcw/4977508)
* Ckmeans : https://github.com/llimllib/ckmeans (https://github.com/simple-statistics/simple-statistics/blob/master/src/ckmeans.js)

But both are terribly slow, even standard kmeans alg. gives better running times.
In contrast, this script works in a reasonable time. 
"""

import math


def kmeans1d(data, k, cutoff=0.1):
		
	# Step 1: Create k clusters with quantile classification
	n = len(data)
	q = int(math.ceil(n/k))
	clusters = [data[i:q+i] for i in range(0,n,q)]

	#Centroid = mean = virtual center point for a group of 1-dimensional values
	centroids = [sum(c) / len(c) for c in clusters]

	# Loop through the dataset until the clusters stabilize
	loopCounter = 0
	while True:		
		# Start counting loops
		loopCounter += 1
		
		# Step 2 : for each cluster...
		for i in range(k-1):
			c1 = clusters[i] #current cluster
			c2 = clusters[i+1] #next cluster
			
			# Test the distance between the right border of the current cluster and the neightbors centroids
			# Move the values if it's closer to the next cluster's centroid. 
			# Then, test the new right border or stop if no more move is needed.
			while True:
				breakValue = c1[-1]#max(c1.values)
				dst1 = abs(breakValue - centroids[i])
				dst2 = abs(breakValue - centroids[i+1])
				if dst1 > dst2:
					v = c1.pop()
					c2.insert(0, v)
				else:
					break
			
			# Test the distance between the left border of the next cluster and the neightbors centroids
			# Move the values if it's closer to the previous cluster's centroid. 
			# Then, test the new left border or stop if no more move is needed.					
			while True:
				breakValue = c2[0]
				dst1 = abs(breakValue - centroids[i])
				dst2 = abs(breakValue - centroids[i+1])
				if dst2 > dst1:
					v = c2.pop(0)
					c1.append(v)
				else:
					break
			
					
		# Step 3: update centroids and stop main loop if they have stopped moving much
		biggest_shift = 0
		for i in range(k):
			# Compute cluster centroid according to new affected values
			c = clusters[i]
			newCentroid = sum(c) / len(c)
			# calculate how far the centroid moved in this iteration
			shift = abs(newCentroid - centroids[i])
			# Keep track of the largest move from all cluster centroid updates
			biggest_shift = max(biggest_shift, shift)
			# Update centroid value
			centroids[i] = newCentroid
		# If the centroids have stopped moving much, say we're done!
		if biggest_shift < cutoff:
			print("Converged after %s iterations" % loopCounter)
			break

	return clusters

