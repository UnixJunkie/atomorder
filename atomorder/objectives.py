"""
atomorder/objectives.py

all scoring functions (objectives)

"""

import numpy as np
import scipy.optimize
from . import settings

# TODO options ignore monovalent / ignore hydrogens

class Rotation(object):
    """
    Rotation(M)

    Objective based on how well reactants and products can be aligned to each other.

    Based on Gold et al. 1998 doi:10.1016/S0031-3203(98)80010-1 and
    Walker et al. 1991 doi:10.1016/1049-9660(91)90036-O

    Parameters:
    -----------
    M: object
        Ordering object

    Attributes:
    -----------
    M: object
        Ordering object
    X: array
        N*3 sized array with reactant coordinates
    Y: array
        N*3 sized array with product coordinates
    reactant_hydrogen_mask: array
        bool array where all reactant non-hydrogen atoms are True
    product_hydrogen_mask: array
        bool array where all product non-hydrogen atoms are True
    W: array
        Page 363 Walker91
    Q: array
        Page 363 Walker91
    Qt_dot_W: array
        Page 363 Walker91
    W_minus_Q: array
        Page 363 Walker91
    q: array
        Each rotation and transformation is defined by a dual quaternion.
        q is the set of all quaternions, where q[0,0] = s1, q[0,1] = r1, q[1,0] = s2 etc.
    # TODO update


    """

    def __init__(self, M):
        self.M = M
        self.X = self.M.products_coordinates
        self.Y = self.M.reactants_coordinates
        #self.reactant_hydrogen_mask = (self.M.reactants_elements != "H") & (self.M.reactants_elements != "D")
        #self.product_hydrogen_mask = (self.M.products_elements != "H") & (self.M.products_elements != "D")
        self.score = self.set_solver()
        self.q = self.initialize_quaternions()
        self.W, self.Q, self.Qt_dot_W, self.W_minus_Q = self.interaction_arrays()
        self.squared_distances = np.zeros(self.M.match_matrix.shape, dtype=float)

    def initialize_quaternions(self):
        """
        Each transformation (rotation+translation) is described by a dual quaternion pair (s,r).
        self.q holds all dual quaternions needed for all the transformations, such that
        self.q = np.concatenate([s1,r1,s2,r2,...]).
        For N reactants and M products, (N+M-1) transformations is required.

        """
        # initialize as s = (0,0,0,0) and r = (0,0,0,1)
        N, M = self.M.num_reactants, self.M.num_products
        q = np.zeros((N+M-1, 2, 4))
        q[:,1,3] = 1
        return q

    def set_solver(self):
        """
        Sets analytical, iterative or numerical solver
        based on the number of reactants and products

        """
        # TODO: solve general case analytically or iterative solver
        if self.M.num_reactants == 1 or self.M.num_products == 1:
            return self.analytical_solver
        else:
            return self.numerical_solver

    def analytical_solver(self, match):
        """
        See page 363 Walker91

        Calculate the optimal translation and rotation between
        all reactants and products, given the current
        match matrix.
        Will only give the correct result when there's either only 1 reactant or 1 product

        Parameters:
        -----------
        match: ndarray
            array of atom order probabilities

        Returns:
        --------
        E: float
            Energy

        """

        E = 0

        # Pick first reactant as reference state
        ref_indices = self.M.reactant_subset_indices[0]
        Y0 = self.Y[ref_indices]

        for i, reactant_indices in enumerate(self.M.reactant_subset_indices):
            for j, product_indices in enumerate(self.M.product_subset_indices):
                X = self.X[product_indices]
                Y = self.Y[reactant_indices]
                sub_matrix_indices = np.ix_(reactant_indices, product_indices)
                match_sub_matrix = match[sub_matrix_indices]
                Qt_dot_W = self.Qt_dot_W[sub_matrix_indices]
                W_minus_Q = self.W_minus_Q[sub_matrix_indices]

                C1 = -2*np.sum(match_sub_matrix[:,:,None,None]*Qt_dot_W,axis=(0,1))
                C2 = match_sub_matrix.sum()
                C3 = 2*np.sum(match_sub_matrix[:,:,None,None]*W_minus_Q,axis=(0,1))
                A = 0.5*(C3.T.dot(C3)/(2*C2)-C1-C1.T)
                # TODO remove
                assert(np.allclose(A,A.T))
                eigen = np.linalg.eigh(A)
                r = eigen[1][:,-1]
                # TODO remove
                assert(np.allclose(A.dot(r), eigen[0][-1]*r))
                s = -C3.dot(r)/(2*C2)
                rot, trans = self.transform(r,s)

                self.squared_distances[sub_matrix_indices] =  np.sum((Y[None,:,:] - trans[None,None,:] - rot.dot(X.T).T[:,None,:])**2, axis=2)

        return self.squared_distances

    def numerical_solver(self, match):
        """
        See page 363 Walker91

        Numerical version for multiple reactants and products

        Parameters:
        -----------
        match: ndarray
            array of atom order probabilities

        Returns:
        --------
        E: float
            Energy
        q: ndarray
            array of fitted quaternions

        """

        def objective(flat_q, match, self):#, jac):
            # TODO jacobian could be written in matrix form.

            # size
            N, M = self.M.num_reactants, self.M.num_products

            # energy
            E = 0

            #if jac:
            #    J = np.zeros(8*(N+M-1))

            q = flat_q.reshape(N+M-1,2,4)

            # There's N+M-1 pairs of r,s.
            # construct rotation matrices and translation vectors
            trans = np.zeros((N+M-1, 3))
            rot = np.zeros((N+M-1, 3, 3))
            for j in xrange(M):
                rot[j], trans[j] = self.transform(q[j, 1], q[j, 0])
            for i in xrange(N-1):
                rot[M+i], trans[M+i] = self.transform(q[M+i,1], q[M+i, 0])

            # use reactant 1 as reference
            ref_indices = self.M.reactant_subset_indices[0]
            Y0 = self.Y[ref_indices]

            for j, product_indices in enumerate(self.M.product_subset_indices):
                # contribution between products and reactant 1
                X = self.X[product_indices]
                #match_sub_matrix = match[np.ix_(ref_indices, product_indices)]
                #E += np.sum(match_sub_matrix*(-2*q[j,1,0]*(q[j,0,1]*X[:,None,2] - q[j,0,2]*X[:,None,1] + q[j,0,3]*X[:,None,0]) - 2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*Y0[None,:,0] + q[j,1,1]*Y0[None,:,1] + q[j,1,2]*Y0[None,:,2]) + X[:,None,1]*(-q[j,1,0]*Y0[None,:,1] + q[j,1,1]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,2]) - X[:,None,2]*(q[j,1,0]*Y0[None,:,2] - q[j,1,2]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,1])) - 2*q[j,1,1]*(-q[j,0,0]*X[:,None,2] + q[j,0,2]*X[:,None,0] + q[j,0,3]*X[:,None,1]) - 2*q[j,1,1]*(-X[:,None,0]*(-q[j,1,0]*Y0[None,:,1] + q[j,1,1]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,2]) + X[:,None,1]*(q[j,1,0]*Y0[None,:,0] + q[j,1,1]*Y0[None,:,1] + q[j,1,2]*Y0[None,:,2]) + X[:,None,2]*(-q[j,1,1]*Y0[None,:,2] + q[j,1,2]*Y0[None,:,1] + q[j,1,3]*Y0[None,:,0])) - 2*q[j,1,2]*(q[j,0,0]*X[:,None,1] - q[j,0,1]*X[:,None,0] + q[j,0,3]*X[:,None,2]) - 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*Y0[None,:,2] - q[j,1,2]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,1]) - X[:,None,1]*(-q[j,1,1]*Y0[None,:,2] + q[j,1,2]*Y0[None,:,1] + q[j,1,3]*Y0[None,:,0]) + X[:,None,2]*(q[j,1,0]*Y0[None,:,0] + q[j,1,1]*Y0[None,:,1] + q[j,1,2]*Y0[None,:,2])) + 2*q[j,1,3]*(q[j,0,0]*X[:,None,0] + q[j,0,1]*X[:,None,1] + q[j,0,2]*X[:,None,2]) - 2*q[j,1,3]*(X[:,None,0]*(-q[j,1,1]*Y0[None,:,2] + q[j,1,2]*Y0[None,:,1] + q[j,1,3]*Y0[None,:,0]) + X[:,None,1]*(q[j,1,0]*Y0[None,:,2] - q[j,1,2]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,1]) + X[:,None,2]*(-q[j,1,0]*Y0[None,:,1] + q[j,1,1]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,2])) + q[j,0,0]**2 - 2*q[j,0,0]*(-q[j,1,1]*Y0[None,:,2] + q[j,1,2]*Y0[None,:,1] + q[j,1,3]*Y0[None,:,0]) + q[j,0,1]**2 - 2*q[j,0,1]*(q[j,1,0]*Y0[None,:,2] - q[j,1,2]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,1]) + q[j,0,2]**2 - 2*q[j,0,2]*(-q[j,1,0]*Y0[None,:,1] + q[j,1,1]*Y0[None,:,0] + q[j,1,3]*Y0[None,:,2]) + q[j,0,3]**2 + 2*q[j,0,3]*(q[j,1,0]*Y0[None,:,0] + q[j,1,1]*Y0[None,:,1] + q[j,1,2]*Y0[None,:,2]) + X[:,None,0]**2 + X[:,None,1]**2 + X[:,None,2]**2 + Y0[None,:,0]**2 + Y0[None,:,1]**2 + Y0[None,:,2]**2))
                self.squared_distances[np.ix_(ref_indices, product_indices)] = np.sum((Y0[None,:,:] - trans[j][None,None,:] - rot[j].dot(X.T).T[:,None,:])**2, axis=2)

                #if jac:
                #    J[8*j]   += np.sum(match_sub_matrix*(2*q[j,1,1]*X[:,None,2] + 2*q[j,1,1]*Y0[None,:,2] - 2*q[j,1,2]*X[:,None,1] - 2*q[j,1,2]*Y0[None,:,1] + 2*q[j,1,3]*X[:,None,0] - 2*q[j,1,3]*Y0[None,:,0] + 2*q[j,0,0]))
                #    J[8*j+1] += np.sum(match_sub_matrix*(-2*q[j,1,0]*X[:,None,2] - 2*q[j,1,0]*Y0[None,:,2] + 2*q[j,1,2]*X[:,None,0] + 2*q[j,1,2]*Y0[None,:,0] + 2*q[j,1,3]*X[:,None,1] - 2*q[j,1,3]*Y0[None,:,1] + 2*q[j,0,1]))
                #    J[8*j+2] += np.sum(match_sub_matrix*(2*q[j,1,0]*X[:,None,1] + 2*q[j,1,0]*Y0[None,:,1] - 2*q[j,1,1]*X[:,None,0] - 2*q[j,1,1]*Y0[None,:,0] + 2*q[j,1,3]*X[:,None,2] - 2*q[j,1,3]*Y0[None,:,2] + 2*q[j,0,2]))
                #    J[8*j+3] += np.sum(match_sub_matrix*(-2*q[j,1,0]*X[:,None,0] + 2*q[j,1,0]*Y0[None,:,0] - 2*q[j,1,1]*X[:,None,1] + 2*q[j,1,1]*Y0[None,:,1] - 2*q[j,1,2]*X[:,None,2] + 2*q[j,1,2]*Y0[None,:,2] + 2*q[j,0,3]))
                #    J[8*j+4] += np.sum(match_sub_matrix*(-4*q[j,1,0]*X[:,None,0]*Y0[None,:,0] + 4*q[j,1,0]*X[:,None,1]*Y0[None,:,1] + 4*q[j,1,0]*X[:,None,2]*Y0[None,:,2] - 4*q[j,1,1]*X[:,None,0]*Y0[None,:,1] - 4*q[j,1,1]*X[:,None,1]*Y0[None,:,0] - 4*q[j,1,2]*X[:,None,0]*Y0[None,:,2] - 4*q[j,1,2]*X[:,None,2]*Y0[None,:,0] - 4*q[j,1,3]*X[:,None,1]*Y0[None,:,2] + 4*q[j,1,3]*X[:,None,2]*Y0[None,:,1] - 2*q[j,0,1]*X[:,None,2] - 2*q[j,0,1]*Y0[None,:,2] + 2*q[j,0,2]*X[:,None,1] + 2*q[j,0,2]*Y0[None,:,1] - 2*q[j,0,3]*X[:,None,0] + 2*q[j,0,3]*Y0[None,:,0]))
                #    J[8*j+5] += np.sum(match_sub_matrix*(-4*q[j,1,0]*X[:,None,0]*Y0[None,:,1] - 4*q[j,1,0]*X[:,None,1]*Y0[None,:,0] + 4*q[j,1,1]*X[:,None,0]*Y0[None,:,0] - 4*q[j,1,1]*X[:,None,1]*Y0[None,:,1] + 4*q[j,1,1]*X[:,None,2]*Y0[None,:,2] - 4*q[j,1,2]*X[:,None,1]*Y0[None,:,2] - 4*q[j,1,2]*X[:,None,2]*Y0[None,:,1] + 4*q[j,1,3]*X[:,None,0]*Y0[None,:,2] - 4*q[j,1,3]*X[:,None,2]*Y0[None,:,0] + 2*q[j,0,0]*X[:,None,2] + 2*q[j,0,0]*Y0[None,:,2] - 2*q[j,0,2]*X[:,None,0] - 2*q[j,0,2]*Y0[None,:,0] - 2*q[j,0,3]*X[:,None,1] + 2*q[j,0,3]*Y0[None,:,1]))
                #    J[8*j+6] += np.sum(match_sub_matrix*(-4*q[j,1,0]*X[:,None,0]*Y0[None,:,2] - 4*q[j,1,0]*X[:,None,2]*Y0[None,:,0] - 4*q[j,1,1]*X[:,None,1]*Y0[None,:,2] - 4*q[j,1,1]*X[:,None,2]*Y0[None,:,1] + 4*q[j,1,2]*X[:,None,0]*Y0[None,:,0] + 4*q[j,1,2]*X[:,None,1]*Y0[None,:,1] - 4*q[j,1,2]*X[:,None,2]*Y0[None,:,2] - 4*q[j,1,3]*X[:,None,0]*Y0[None,:,1] + 4*q[j,1,3]*X[:,None,1]*Y0[None,:,0] - 2*q[j,0,0]*X[:,None,1] - 2*q[j,0,0]*Y0[None,:,1] + 2*q[j,0,1]*X[:,None,0] + 2*q[j,0,1]*Y0[None,:,0] - 2*q[j,0,3]*X[:,None,2] + 2*q[j,0,3]*Y0[None,:,2]))
                #    J[8*j+7] += np.sum(match_sub_matrix*(-4*q[j,1,0]*X[:,None,1]*Y0[None,:,2] + 4*q[j,1,0]*X[:,None,2]*Y0[None,:,1] + 4*q[j,1,1]*X[:,None,0]*Y0[None,:,2] - 4*q[j,1,1]*X[:,None,2]*Y0[None,:,0] - 4*q[j,1,2]*X[:,None,0]*Y0[None,:,1] + 4*q[j,1,2]*X[:,None,1]*Y0[None,:,0] - 4*q[j,1,3]*X[:,None,0]*Y0[None,:,0] - 4*q[j,1,3]*X[:,None,1]*Y0[None,:,1] - 4*q[j,1,3]*X[:,None,2]*Y0[None,:,2] + 2*q[j,0,0]*X[:,None,0] - 2*q[j,0,0]*Y0[None,:,0] + 2*q[j,0,1]*X[:,None,1] - 2*q[j,0,1]*Y0[None,:,1] + 2*q[j,0,2]*X[:,None,2] - 2*q[j,0,2]*Y0[None,:,2]))

                # contributions between products and remaining reactants
                for i, reactant_indices in self.M.reactant_subset_indices[1:]:
                    Y = self.X[reactant_indices]
                    #match_sub_matrix = match[np.ix_(reactant_indices, product_indices)]
                    self.squared_distances[np.ix_(reactant_indices, product_indices)] = np.sum((trans[M+i][None,None,:] + (rot[M+i].dot(Y.T).T)[None,:,:] - trans[j][None,None,:] - (rot[j].dot(X.T).T)[:,None,:])**2, axis=2)

                    #if jac:
                    #    J[8*j]       += np.sum(match_sub_matrix[:,:,None]*(-2*q[j,1,0]*(q[M+i,1,0]*q[M+i,0,0] + q[M+i,1,1]*q[M+i,0,1] + q[M+i,1,2]*q[M+i,0,2] + q[M+i,1,3]*q[M+i,0,3]) - 2*q[j,1,0]*(q[M+i,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,1,1]*X[:,None,2] + 2*q[j,1,1]*(q[M+i,1,0]*q[M+i,0,1] - q[M+i,1,1]*q[M+i,0,0] - q[M+i,1,2]*q[M+i,0,3] + q[M+i,1,3]*q[M+i,0,2]) + 2*q[j,1,1]*(q[M+i,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[M+i,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - 2*q[j,1,2]*X[:,None,1] + 2*q[j,1,2]*(q[M+i,1,0]*q[M+i,0,2] + q[M+i,1,1]*q[M+i,0,3] - q[M+i,1,2]*q[M+i,0,0] - q[M+i,1,3]*q[M+i,0,1]) - 2*q[j,1,2]*(-q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + 2*q[j,1,3]*X[:,None,0] + 2*q[j,1,3]*(q[M+i,1,0]*q[M+i,0,3] - q[M+i,1,1]*q[M+i,0,2] + q[M+i,1,2]*q[M+i,0,1] - q[M+i,1,3]*q[M+i,0,0]) - 2*q[j,1,3]*(q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + 2*q[j,0,0]))
                    #    J[8*j+1]     += np.sum(match_sub_matrix[:,:,None]*(-2*q[j,1,0]*X[:,None,2] - 2*q[j,1,0]*(q[M+i,1,0]*q[M+i,0,1] - q[M+i,1,1]*q[M+i,0,0] - q[M+i,1,2]*q[M+i,0,3] + q[M+i,1,3]*q[M+i,0,2]) - 2*q[j,1,0]*(q[M+i,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[M+i,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - 2*q[j,1,1]*(q[M+i,1,0]*q[M+i,0,0] + q[M+i,1,1]*q[M+i,0,1] + q[M+i,1,2]*q[M+i,0,2] + q[M+i,1,3]*q[M+i,0,3]) - 2*q[j,1,1]*(q[M+i,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,1,2]*X[:,None,0] - 2*q[j,1,2]*(q[M+i,1,0]*q[M+i,0,3] - q[M+i,1,1]*q[M+i,0,2] + q[M+i,1,2]*q[M+i,0,1] - q[M+i,1,3]*q[M+i,0,0]) + 2*q[j,1,2]*(q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + 2*q[j,1,3]*X[:,None,1] + 2*q[j,1,3]*(q[M+i,1,0]*q[M+i,0,2] + q[M+i,1,1]*q[M+i,0,3] - q[M+i,1,2]*q[M+i,0,0] - q[M+i,1,3]*q[M+i,0,1]) - 2*q[j,1,3]*(-q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + 2*q[j,0,1]))
                    #    J[8*j+2]     += np.sum(match_sub_matrix[:,:,None]*(2*q[j,1,0]*X[:,None,1] - 2*q[j,1,0]*(q[M+i,1,0]*q[M+i,0,2] + q[M+i,1,1]*q[M+i,0,3] - q[M+i,1,2]*q[M+i,0,0] - q[M+i,1,3]*q[M+i,0,1]) + 2*q[j,1,0]*(-q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - 2*q[j,1,1]*X[:,None,0] + 2*q[j,1,1]*(q[M+i,1,0]*q[M+i,0,3] - q[M+i,1,1]*q[M+i,0,2] + q[M+i,1,2]*q[M+i,0,1] - q[M+i,1,3]*q[M+i,0,0]) - 2*q[j,1,1]*(q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - 2*q[j,1,2]*(q[M+i,1,0]*q[M+i,0,0] + q[M+i,1,1]*q[M+i,0,1] + q[M+i,1,2]*q[M+i,0,2] + q[M+i,1,3]*q[M+i,0,3]) - 2*q[j,1,2]*(q[M+i,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,1,3]*X[:,None,2] - 2*q[j,1,3]*(q[M+i,1,0]*q[M+i,0,1] - q[M+i,1,1]*q[M+i,0,0] - q[M+i,1,2]*q[M+i,0,3] + q[M+i,1,3]*q[M+i,0,2]) - 2*q[j,1,3]*(q[M+i,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[M+i,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + 2*q[j,0,2]))
                    #    J[8*j+3]     += np.sum(match_sub_matrix[:,:,None]*(-2*q[j,1,0]*X[:,None,0] - 2*q[j,1,0]*(q[M+i,1,0]*q[M+i,0,3] - q[M+i,1,1]*q[M+i,0,2] + q[M+i,1,2]*q[M+i,0,1] - q[M+i,1,3]*q[M+i,0,0]) + 2*q[j,1,0]*(q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - 2*q[j,1,1]*X[:,None,1] - 2*q[j,1,1]*(q[M+i,1,0]*q[M+i,0,2] + q[M+i,1,1]*q[M+i,0,3] - q[M+i,1,2]*q[M+i,0,0] - q[M+i,1,3]*q[M+i,0,1]) + 2*q[j,1,1]*(-q[M+i,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[M+i,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - 2*q[j,1,2]*X[:,None,2] + 2*q[j,1,2]*(q[M+i,1,0]*q[M+i,0,1] - q[M+i,1,1]*q[M+i,0,0] - q[M+i,1,2]*q[M+i,0,3] + q[M+i,1,3]*q[M+i,0,2]) + 2*q[j,1,2]*(q[M+i,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[M+i,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - 2*q[j,1,3]*(q[M+i,1,0]*q[M+i,0,0] + q[M+i,1,1]*q[M+i,0,1] + q[M+i,1,2]*q[M+i,0,2] + q[M+i,1,3]*q[M+i,0,3]) - 2*q[j,1,3]*(q[M+i,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[M+i,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[M+i,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[M+i,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,0,3]))
                    #    J[8*j+4]     += np.sum(match_sub_matrix[:,:,None]*(-4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,2] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,1] + 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,1] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] - 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,0] - 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,1] + 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] + 8*q[j,1,0]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,1] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,0] - 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,0] + 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,1] + 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] + 8*q[j,1,1]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] - 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,1] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,1] + 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,2] - 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,0] + 8*q[j,1,2]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] + 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,0] - 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,0] - 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,2] - 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,1] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,1] + 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] + 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] + 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,1] + 8*q[j,1,3]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] + 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,1] + 2*q[M+i,1,0]**2*q[j,0,1]*Y[None,:,2] - 2*q[M+i,1,0]**2*q[j,0,2]*Y[None,:,1] + 2*q[M+i,1,0]**2*q[j,0,3]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,2]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,3]*Y[None,:,1] - 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,1]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,3]*Y[None,:,2] - 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,1]*Y[None,:,1] - 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,2]*Y[None,:,2] - 2*q[M+i,1,0]*q[j,0,0]*q[M+i,0,0] - 2*q[M+i,1,0]*q[j,0,1]*q[M+i,0,1] - 2*q[M+i,1,0]*q[j,0,2]*q[M+i,0,2] - 2*q[M+i,1,0]*q[j,0,3]*q[M+i,0,3] + 2*q[M+i,1,1]**2*q[j,0,1]*Y[None,:,2] + 2*q[M+i,1,1]**2*q[j,0,2]*Y[None,:,1] - 2*q[M+i,1,1]**2*q[j,0,3]*Y[None,:,0] - 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,1]*Y[None,:,1] + 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,2]*Y[None,:,2] + 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,1]*Y[None,:,0] + 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,3]*Y[None,:,2] - 2*q[M+i,1,1]*q[j,0,0]*q[M+i,0,1] + 2*q[M+i,1,1]*q[j,0,1]*q[M+i,0,0] - 2*q[M+i,1,1]*q[j,0,2]*q[M+i,0,3] + 2*q[M+i,1,1]*q[j,0,3]*q[M+i,0,2] - 2*q[M+i,1,2]**2*q[j,0,1]*Y[None,:,2] - 2*q[M+i,1,2]**2*q[j,0,2]*Y[None,:,1] - 2*q[M+i,1,2]**2*q[j,0,3]*Y[None,:,0] + 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,2]*Y[None,:,0] - 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,3]*Y[None,:,1] - 2*q[M+i,1,2]*q[j,0,0]*q[M+i,0,2] + 2*q[M+i,1,2]*q[j,0,1]*q[M+i,0,3] + 2*q[M+i,1,2]*q[j,0,2]*q[M+i,0,0] - 2*q[M+i,1,2]*q[j,0,3]*q[M+i,0,1] - 2*q[M+i,1,3]**2*q[j,0,1]*Y[None,:,2] + 2*q[M+i,1,3]**2*q[j,0,2]*Y[None,:,1] + 2*q[M+i,1,3]**2*q[j,0,3]*Y[None,:,0] - 2*q[M+i,1,3]*q[j,0,0]*q[M+i,0,3] - 2*q[M+i,1,3]*q[j,0,1]*q[M+i,0,2] + 2*q[M+i,1,3]*q[j,0,2]*q[M+i,0,1] + 2*q[M+i,1,3]*q[j,0,3]*q[M+i,0,0] - 2*q[j,0,1]*X[:,None,2] + 2*q[j,0,2]*X[:,None,1] - 2*q[j,0,3]*X[:,None,0]))
                    #    J[8*j+5]     += np.sum(match_sub_matrix[:,:,None]*(4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,1] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] + 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] + 8*q[j,1,0]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] - 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,0] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,0] - 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,0] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,0] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,0] - 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,2] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,1] + 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,2] - 8*q[j,1,1]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,0] - 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,2] + 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,1] + 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] - 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,1] + 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,1] - 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] + 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,1] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,2]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] - 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,1] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,0] + 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,1] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,0] + 8*q[j,1,3]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,0] - 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,0] - 2*q[M+i,1,0]**2*q[j,0,0]*Y[None,:,2] - 2*q[M+i,1,0]**2*q[j,0,2]*Y[None,:,0] - 2*q[M+i,1,0]**2*q[j,0,3]*Y[None,:,1] - 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,2]*Y[None,:,1] + 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,3]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,0]*Y[None,:,0] - 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,2]*Y[None,:,2] + 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,0]*Y[None,:,1] - 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,3]*Y[None,:,2] + 2*q[M+i,1,0]*q[j,0,0]*q[M+i,0,1] - 2*q[M+i,1,0]*q[j,0,1]*q[M+i,0,0] + 2*q[M+i,1,0]*q[j,0,2]*q[M+i,0,3] - 2*q[M+i,1,0]*q[j,0,3]*q[M+i,0,2] - 2*q[M+i,1,1]**2*q[j,0,0]*Y[None,:,2] + 2*q[M+i,1,1]**2*q[j,0,2]*Y[None,:,0] + 2*q[M+i,1,1]**2*q[j,0,3]*Y[None,:,1] + 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,0]*Y[None,:,1] + 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,3]*Y[None,:,2] - 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,0]*Y[None,:,0] - 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,2]*Y[None,:,2] - 2*q[M+i,1,1]*q[j,0,0]*q[M+i,0,0] - 2*q[M+i,1,1]*q[j,0,1]*q[M+i,0,1] - 2*q[M+i,1,1]*q[j,0,2]*q[M+i,0,2] - 2*q[M+i,1,1]*q[j,0,3]*q[M+i,0,3] + 2*q[M+i,1,2]**2*q[j,0,0]*Y[None,:,2] + 2*q[M+i,1,2]**2*q[j,0,2]*Y[None,:,0] - 2*q[M+i,1,2]**2*q[j,0,3]*Y[None,:,1] + 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,2]*Y[None,:,1] + 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,3]*Y[None,:,0] - 2*q[M+i,1,2]*q[j,0,0]*q[M+i,0,3] - 2*q[M+i,1,2]*q[j,0,1]*q[M+i,0,2] + 2*q[M+i,1,2]*q[j,0,2]*q[M+i,0,1] + 2*q[M+i,1,2]*q[j,0,3]*q[M+i,0,0] + 2*q[M+i,1,3]**2*q[j,0,0]*Y[None,:,2] - 2*q[M+i,1,3]**2*q[j,0,2]*Y[None,:,0] + 2*q[M+i,1,3]**2*q[j,0,3]*Y[None,:,1] + 2*q[M+i,1,3]*q[j,0,0]*q[M+i,0,2] - 2*q[M+i,1,3]*q[j,0,1]*q[M+i,0,3] - 2*q[M+i,1,3]*q[j,0,2]*q[M+i,0,0] + 2*q[M+i,1,3]*q[j,0,3]*q[M+i,0,1] + 2*q[j,0,0]*X[:,None,2] - 2*q[j,0,2]*X[:,None,0] - 2*q[j,0,3]*X[:,None,1]))
                    #    J[8*j+6]     += np.sum(match_sub_matrix[:,:,None]*(4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,1] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] - 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,2] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,1] + 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] + 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,0] + 8*q[j,1,0]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,2] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,0] - 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,0] - 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,1] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] + 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,1] + 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,1] - 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,2] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,1] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,0] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,0] - 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,2] + 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] - 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,1] + 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] + 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,0] - 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,2] - 8*q[j,1,2]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] + 8*q[j,1,2]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] + 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,2] + 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,0] + 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,0] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,1] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] + 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,0] - 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] + 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] + 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] - 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,0] + 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,0] + 2*q[M+i,1,0]**2*q[j,0,0]*Y[None,:,1] + 2*q[M+i,1,0]**2*q[j,0,1]*Y[None,:,0] - 2*q[M+i,1,0]**2*q[j,0,3]*Y[None,:,2] - 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,0]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,1]*Y[None,:,1] + 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,1]*Y[None,:,2] + 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,3]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,0]*Y[None,:,2] + 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,3]*Y[None,:,1] + 2*q[M+i,1,0]*q[j,0,0]*q[M+i,0,2] - 2*q[M+i,1,0]*q[j,0,1]*q[M+i,0,3] - 2*q[M+i,1,0]*q[j,0,2]*q[M+i,0,0] + 2*q[M+i,1,0]*q[j,0,3]*q[M+i,0,1] - 2*q[M+i,1,1]**2*q[j,0,0]*Y[None,:,1] - 2*q[M+i,1,1]**2*q[j,0,1]*Y[None,:,0] - 2*q[M+i,1,1]**2*q[j,0,3]*Y[None,:,2] - 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,0]*Y[None,:,2] + 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,3]*Y[None,:,1] + 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,1]*Y[None,:,2] - 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,3]*Y[None,:,0] + 2*q[M+i,1,1]*q[j,0,0]*q[M+i,0,3] + 2*q[M+i,1,1]*q[j,0,1]*q[M+i,0,2] - 2*q[M+i,1,1]*q[j,0,2]*q[M+i,0,1] - 2*q[M+i,1,1]*q[j,0,3]*q[M+i,0,0] + 2*q[M+i,1,2]**2*q[j,0,0]*Y[None,:,1] - 2*q[M+i,1,2]**2*q[j,0,1]*Y[None,:,0] + 2*q[M+i,1,2]**2*q[j,0,3]*Y[None,:,2] - 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,0]*Y[None,:,0] - 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,1]*Y[None,:,1] - 2*q[M+i,1,2]*q[j,0,0]*q[M+i,0,0] - 2*q[M+i,1,2]*q[j,0,1]*q[M+i,0,1] - 2*q[M+i,1,2]*q[j,0,2]*q[M+i,0,2] - 2*q[M+i,1,2]*q[j,0,3]*q[M+i,0,3] - 2*q[M+i,1,3]**2*q[j,0,0]*Y[None,:,1] + 2*q[M+i,1,3]**2*q[j,0,1]*Y[None,:,0] + 2*q[M+i,1,3]**2*q[j,0,3]*Y[None,:,2] - 2*q[M+i,1,3]*q[j,0,0]*q[M+i,0,1] + 2*q[M+i,1,3]*q[j,0,1]*q[M+i,0,0] - 2*q[M+i,1,3]*q[j,0,2]*q[M+i,0,3] + 2*q[M+i,1,3]*q[j,0,3]*q[M+i,0,2] - 2*q[j,0,0]*X[:,None,1] + 2*q[j,0,1]*X[:,None,0] - 2*q[j,0,3]*X[:,None,2]))
                    #    J[8*j+7]     += np.sum(match_sub_matrix[:,:,None]*(4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,1] + 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,0] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] - 8*q[j,1,0]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,0]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,0]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,1] - 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,1] + 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] + 8*q[j,1,0]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] + 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,0]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,2] - 4*q[j,1,0]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,1] + 8*q[j,1,0]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,0]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,2] + 4*q[j,1,0]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,1] + 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,0]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,1] - 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,2]*Y[None,:,1] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,2] + 8*q[j,1,1]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,1]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,0] + 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,1] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,1]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,1]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,2] + 4*q[j,1,1]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,0] + 8*q[j,1,1]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] + 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,2] - 4*q[j,1,1]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,2] - 4*q[j,1,1]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,0] - 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,2] + 4*q[j,1,1]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,2]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,0] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,1] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] + 8*q[j,1,2]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,0] - 4*q[j,1,2]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] + 8*q[j,1,2]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,2]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,0] - 8*q[j,1,2]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,1] - 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,2]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,1] + 4*q[j,1,2]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,0] + 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,1] - 4*q[j,1,2]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,0] - 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,0]**2*X[:,None,2]*Y[None,:,2] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,0]*Y[None,:,1] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,1]*X[:,None,1]*Y[None,:,0] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,0]*Y[None,:,2] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,2]*X[:,None,2]*Y[None,:,0] + 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,1]*Y[None,:,2] - 8*q[j,1,3]*q[M+i,1,0]*q[M+i,1,3]*X[:,None,2]*Y[None,:,1] - 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,1]*X[:,None,2] + 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,2]*X[:,None,1] + 4*q[j,1,3]*q[M+i,1,0]*q[M+i,0,3]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,1]*Y[None,:,1] + 4*q[j,1,3]*q[M+i,1,1]**2*X[:,None,2]*Y[None,:,2] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,1]*Y[None,:,2] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,2]*X[:,None,2]*Y[None,:,1] - 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,0]*Y[None,:,2] + 8*q[j,1,3]*q[M+i,1,1]*q[M+i,1,3]*X[:,None,2]*Y[None,:,0] + 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,0]*X[:,None,2] - 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,2]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,1]*q[M+i,0,3]*X[:,None,1] + 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,0]*Y[None,:,0] + 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,3]*q[M+i,1,2]**2*X[:,None,2]*Y[None,:,2] + 8*q[j,1,3]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,0]*Y[None,:,1] - 8*q[j,1,3]*q[M+i,1,2]*q[M+i,1,3]*X[:,None,1]*Y[None,:,0] - 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,0]*X[:,None,1] + 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,1]*X[:,None,0] + 4*q[j,1,3]*q[M+i,1,2]*q[M+i,0,3]*X[:,None,2] - 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,0]*Y[None,:,0] - 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,1]*Y[None,:,1] - 4*q[j,1,3]*q[M+i,1,3]**2*X[:,None,2]*Y[None,:,2] - 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,0]*X[:,None,0] - 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,1]*X[:,None,1] - 4*q[j,1,3]*q[M+i,1,3]*q[M+i,0,2]*X[:,None,2] - 2*q[M+i,1,0]**2*q[j,0,0]*Y[None,:,0] + 2*q[M+i,1,0]**2*q[j,0,1]*Y[None,:,1] + 2*q[M+i,1,0]**2*q[j,0,2]*Y[None,:,2] - 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,0]*Y[None,:,1] - 4*q[M+i,1,0]*q[M+i,1,1]*q[j,0,1]*Y[None,:,0] - 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,0]*Y[None,:,2] - 4*q[M+i,1,0]*q[M+i,1,2]*q[j,0,2]*Y[None,:,0] + 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,1]*Y[None,:,2] - 4*q[M+i,1,0]*q[M+i,1,3]*q[j,0,2]*Y[None,:,1] + 2*q[M+i,1,0]*q[j,0,0]*q[M+i,0,3] + 2*q[M+i,1,0]*q[j,0,1]*q[M+i,0,2] - 2*q[M+i,1,0]*q[j,0,2]*q[M+i,0,1] - 2*q[M+i,1,0]*q[j,0,3]*q[M+i,0,0] + 2*q[M+i,1,1]**2*q[j,0,0]*Y[None,:,0] - 2*q[M+i,1,1]**2*q[j,0,1]*Y[None,:,1] + 2*q[M+i,1,1]**2*q[j,0,2]*Y[None,:,2] - 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,1]*Y[None,:,2] - 4*q[M+i,1,1]*q[M+i,1,2]*q[j,0,2]*Y[None,:,1] - 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,0]*Y[None,:,2] + 4*q[M+i,1,1]*q[M+i,1,3]*q[j,0,2]*Y[None,:,0] - 2*q[M+i,1,1]*q[j,0,0]*q[M+i,0,2] + 2*q[M+i,1,1]*q[j,0,1]*q[M+i,0,3] + 2*q[M+i,1,1]*q[j,0,2]*q[M+i,0,0] - 2*q[M+i,1,1]*q[j,0,3]*q[M+i,0,1] + 2*q[M+i,1,2]**2*q[j,0,0]*Y[None,:,0] + 2*q[M+i,1,2]**2*q[j,0,1]*Y[None,:,1] - 2*q[M+i,1,2]**2*q[j,0,2]*Y[None,:,2] + 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,0]*Y[None,:,1] - 4*q[M+i,1,2]*q[M+i,1,3]*q[j,0,1]*Y[None,:,0] + 2*q[M+i,1,2]*q[j,0,0]*q[M+i,0,1] - 2*q[M+i,1,2]*q[j,0,1]*q[M+i,0,0] + 2*q[M+i,1,2]*q[j,0,2]*q[M+i,0,3] - 2*q[M+i,1,2]*q[j,0,3]*q[M+i,0,2] - 2*q[M+i,1,3]**2*q[j,0,0]*Y[None,:,0] - 2*q[M+i,1,3]**2*q[j,0,1]*Y[None,:,1] - 2*q[M+i,1,3]**2*q[j,0,2]*Y[None,:,2] - 2*q[M+i,1,3]*q[j,0,0]*q[M+i,0,0] - 2*q[M+i,1,3]*q[j,0,1]*q[M+i,0,1] - 2*q[M+i,1,3]*q[j,0,2]*q[M+i,0,2] - 2*q[M+i,1,3]*q[j,0,3]*q[M+i,0,3] + 2*q[j,0,0]*X[:,None,0] + 2*q[j,0,1]*X[:,None,1] + 2*q[j,0,2]*X[:,None,2]))
                    #    J[8*(M+i)]   += np.sum(match_sub_matrix[:,:,None]*(-2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) - X[:,None,1]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2])) - 2*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3])) + 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) - X[:,None,2]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0])) + 2*q[j,1,3]*(-X[:,None,0]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1])) + 2*q[M+i,1,1]*Y[None,:,2] - 2*q[M+i,1,2]*Y[None,:,1] + 2*q[M+i,1,3]*Y[None,:,0] - 2*q[j,0,0]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + 2*q[j,0,1]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + 2*q[j,0,2]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + 2*q[j,0,3]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) + 2*q[M+i,0,0]))
                    #    J[8*(M+i)+1] += np.sum(match_sub_matrix[:,:,None]*(2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3])) - 2*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) - X[:,None,1]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2])) + 2*q[j,1,2]*(-X[:,None,0]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1])) - 2*q[j,1,3]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) - X[:,None,2]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0])) - 2*q[M+i,1,0]*Y[None,:,2] + 2*q[M+i,1,2]*Y[None,:,0] + 2*q[M+i,1,3]*Y[None,:,1] - 2*q[j,0,0]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) - 2*q[j,0,1]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + 2*q[j,0,2]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) - 2*q[j,0,3]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + 2*q[M+i,0,1]))
                    #    J[8*(M+1)+2] += np.sum(match_sub_matrix[:,:,None]*(-2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) - X[:,None,2]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0])) - 2*q[j,1,1]*(-X[:,None,0]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1])) - 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) - X[:,None,1]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2])) - 2*q[j,1,3]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3])) + 2*q[M+i,1,0]*Y[None,:,1] - 2*q[M+i,1,1]*Y[None,:,0] + 2*q[M+i,1,3]*Y[None,:,2] - 2*q[j,0,0]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) - 2*q[j,0,1]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) - 2*q[j,0,2]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + 2*q[j,0,3]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + 2*q[M+i,0,2]))
                    #    J[8*(M+1)+3] += np.sum(match_sub_matrix[:,:,None]*(-2*q[j,1,0]*(-X[:,None,0]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1])) + 2*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) - X[:,None,2]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0])) + 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,1]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3])) - 2*q[j,1,3]*(X[:,None,0]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) - X[:,None,1]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) + X[:,None,2]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2])) - 2*q[M+i,1,0]*Y[None,:,0] - 2*q[M+i,1,1]*Y[None,:,1] - 2*q[M+i,1,2]*Y[None,:,2] - 2*q[j,0,0]*(q[j,1,0]*q[M+i,1,3] + q[j,1,1]*q[M+i,1,2] - q[j,1,2]*q[M+i,1,1] - q[j,1,3]*q[M+i,1,0]) + 2*q[j,0,1]*(q[j,1,0]*q[M+i,1,2] - q[j,1,1]*q[M+i,1,3] - q[j,1,2]*q[M+i,1,0] + q[j,1,3]*q[M+i,1,1]) - 2*q[j,0,2]*(q[j,1,0]*q[M+i,1,1] - q[j,1,1]*q[M+i,1,0] + q[j,1,2]*q[M+i,1,3] - q[j,1,3]*q[M+i,1,2]) - 2*q[j,0,3]*(q[j,1,0]*q[M+i,1,0] + q[j,1,1]*q[M+i,1,1] + q[j,1,2]*q[M+i,1,2] + q[j,1,3]*q[M+i,1,3]) + 2*q[M+i,0,3]))
                    #    J[8*(M+1)+4] += np.sum(match_sub_matrix[:,:,None]*(-4*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + X[:,None,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + X[:,None,2]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]))) + 2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] - q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) - X[:,None,1]*(q[j,1,0]*q[M+i,0,2] - q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] - q[j,1,3]*q[M+i,0,2])) + 4*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - X[:,None,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + X[:,None,2]*(q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]))) + 2*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,2] - q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] - q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) + X[:,None,2]*(-q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3])) - 4*q[j,1,2]*(-X[:,None,0]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + X[:,None,1]*(q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]))) - 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] - q[j,1,3]*q[M+i,0,2]) + X[:,None,1]*(-q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) - X[:,None,2]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] - q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0])) + 4*q[j,1,3]*(X[:,None,0]*(q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,1]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - X[:,None,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]))) - 2*q[j,1,3]*(-X[:,None,0]*(-q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] - q[j,1,3]*q[M+i,0,2]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,2] - q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1])) + 4*q[j,0,0]*(q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,0,0]*(-q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + 4*q[j,0,1]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - 2*q[j,0,1]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] - q[j,1,3]*q[M+i,0,2]) - 4*q[j,0,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - 2*q[j,0,2]*(q[j,1,0]*q[M+i,0,2] - q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) + 4*q[j,0,3]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - 2*q[j,0,3]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] - q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) - 2*q[M+i,0,1]*Y[None,:,2] + 2*q[M+i,0,2]*Y[None,:,1] - 2*q[M+i,0,3]*Y[None,:,0]))
                    #    J[8*(M+1)+5] += np.sum(match_sub_matrix[:,:,None]*(-4*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - X[:,None,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,2]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]))) - 2*q[j,1,0]*(-X[:,None,0]*(-q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] - q[j,1,3]*q[M+i,0,0]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,0] - q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3])) - 4*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,2]*(q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]))) + 2*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] - q[j,1,3]*q[M+i,0,0]) + X[:,None,1]*(-q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) - X[:,None,2]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] - q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2])) + 4*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,1]*(q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - X[:,None,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]))) + 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,0] - q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] - q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) + X[:,None,2]*(-q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1])) + 4*q[j,1,3]*(-X[:,None,0]*(q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + X[:,None,1]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]))) - 2*q[j,1,3]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] - q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) - X[:,None,1]*(q[j,1,0]*q[M+i,0,0] - q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] - q[j,1,3]*q[M+i,0,0])) - 4*q[j,0,0]*(q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - 2*q[j,0,0]*(q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] - q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) + 4*q[j,0,1]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,0,1]*(q[j,1,0]*q[M+i,0,0] - q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + 4*q[j,0,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - 2*q[j,0,2]*(q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] - q[j,1,3]*q[M+i,0,0]) + 4*q[j,0,3]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - 2*q[j,0,3]*(-q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) + 2*q[M+i,0,0]*Y[None,:,2] - 2*q[M+i,0,2]*Y[None,:,0] - 2*q[M+i,0,3]*Y[None,:,1]))
                    #    J[8*(M+1)+6] += np.sum(match_sub_matrix[:,:,None]*(4*q[j,1,0]*(-X[:,None,0]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,1]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]))) + 2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,1] - q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] - q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + X[:,None,2]*(-q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0])) - 4*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + X[:,None,1]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) - X[:,None,2]*(q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]))) - 2*q[j,1,1]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] - q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) - X[:,None,1]*(q[j,1,0]*q[M+i,0,1] - q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] - q[j,1,3]*q[M+i,0,1])) - 4*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,1]*(q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + X[:,None,2]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]))) + 2*q[j,1,2]*(-X[:,None,0]*(-q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] - q[j,1,3]*q[M+i,0,1]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,1] - q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2])) + 4*q[j,1,3]*(X[:,None,0]*(q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - X[:,None,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,2]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]))) - 2*q[j,1,3]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] - q[j,1,3]*q[M+i,0,1]) + X[:,None,1]*(-q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) - X[:,None,2]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] - q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3])) + 4*q[j,0,0]*(q[j,1,1]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - 2*q[j,0,0]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] + q[j,1,2]*q[M+i,0,0] - q[j,1,3]*q[M+i,0,1]) - 4*q[j,0,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - 2*q[j,0,1]*(-q[j,1,0]*q[M+i,0,3] + q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) + 4*q[j,0,2]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) - q[j,1,3]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) + 2*q[j,0,2]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] - q[j,1,2]*q[M+i,0,2] + q[j,1,3]*q[M+i,0,3]) + 4*q[j,0,3]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,0] + q[M+i,1,1]*Y[None,:,1] + q[M+i,1,2]*Y[None,:,2])) - 2*q[j,0,3]*(q[j,1,0]*q[M+i,0,1] - q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) - 2*q[M+i,0,0]*Y[None,:,1] + 2*q[M+i,0,1]*Y[None,:,0] - 2*q[M+i,0,3]*Y[None,:,2]))
                    #    J[8*(M+1)+7] += np.sum(match_sub_matrix[:,:,None]*(-4*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + X[:,None,1]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - X[:,None,2]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]))) - 2*q[j,1,0]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] - q[j,1,3]*q[M+i,0,3]) + X[:,None,1]*(-q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) - X[:,None,2]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] - q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1])) - 4*q[j,1,1]*(-X[:,None,0]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + X[:,None,1]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + X[:,None,2]*(-q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]))) - 2*q[j,1,1]*(-X[:,None,0]*(-q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] - q[j,1,3]*q[M+i,0,3]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,3] - q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0])) - 4*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - X[:,None,1]*(-q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,2]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]))) - 2*q[j,1,2]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] - q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) - X[:,None,1]*(q[j,1,0]*q[M+i,0,3] - q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) + X[:,None,2]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] - q[j,1,3]*q[M+i,0,3])) - 4*q[j,1,3]*(X[:,None,0]*(-q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) + X[:,None,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) + X[:,None,2]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]))) - 2*q[j,1,3]*(X[:,None,0]*(q[j,1,0]*q[M+i,0,3] - q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) + X[:,None,1]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] - q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) + X[:,None,2]*(-q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2])) - 4*q[j,0,0]*(-q[j,1,1]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) + q[j,1,2]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,3]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0])) - 2*q[j,0,0]*(q[j,1,0]*q[M+i,0,3] - q[j,1,1]*q[M+i,0,2] + q[j,1,2]*q[M+i,0,1] + q[j,1,3]*q[M+i,0,0]) - 4*q[j,0,1]*(q[j,1,0]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2]) - q[j,1,2]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1])) - 2*q[j,0,1]*(q[j,1,0]*q[M+i,0,2] + q[j,1,1]*q[M+i,0,3] - q[j,1,2]*q[M+i,0,0] + q[j,1,3]*q[M+i,0,1]) - 4*q[j,0,2]*(-q[j,1,0]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,1]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,3]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) - 2*q[j,0,2]*(-q[j,1,0]*q[M+i,0,1] + q[j,1,1]*q[M+i,0,0] + q[j,1,2]*q[M+i,0,3] + q[j,1,3]*q[M+i,0,2]) + 4*q[j,0,3]*(q[j,1,0]*(q[M+i,1,1]*Y[None,:,2] - q[M+i,1,2]*Y[None,:,1] + q[M+i,1,3]*Y[None,:,0]) + q[j,1,1]*(-q[M+i,1,0]*Y[None,:,2] + q[M+i,1,2]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,1]) + q[j,1,2]*(q[M+i,1,0]*Y[None,:,1] - q[M+i,1,1]*Y[None,:,0] + q[M+i,1,3]*Y[None,:,2])) + 2*q[j,0,3]*(q[j,1,0]*q[M+i,0,0] + q[j,1,1]*q[M+i,0,1] + q[j,1,2]*q[M+i,0,2] - q[j,1,3]*q[M+i,0,3]) + 2*q[M+i,0,0]*Y[None,:,0] + 2*q[M+i,0,1]*Y[None,:,1] + 2*q[M+i,0,2]*Y[None,:,2]))

            #if jac:
            #    return E, J

            return np.sum(self.match_matrix*self.squared_distances)



        def rr_constraint_jacobian(x, j, N, M):
            # jacobian for use with SLSQP
            jac = np.zeros(8*(M+N-1))
            jac[8*j+4:8*j+8] = 2*x[8*j+4:8*j+8]
            return jac

        def rs_constraint_jacobian(x, j, N, M):
            # jacobian for use with SLSQP
            jac = np.zeros(8*(M+N-1))
            jac[8*j:8*j+4] = x[8*j+4:8*j+8]
            jac[8*j+4:8*j+8] = x[8*j:8*j+4]
            return jac


        N, M = self.M.num_reactants, self.M.num_products
        # create constraints
        cons = np.empty(2*(N+M-1), dtype=dict)

        for j in range(M+N-1):
            cons[2*j]   = {"type": "eq", "fun": lambda x: np.sum(x[8*j+4:8*j+8]*x[8*j+4:8*j+8]) -1} # r.T*r = 1
            cons[2*j+1] = {"type": "eq", "fun": lambda x: np.sum(x[8*j+4:8*j+8]*x[8*j:8*j+4])} # r.T*s = 0

            # jacobians for SLSQP
            cons[2*j]["jac"] = lambda x: rr_constraint_jacobian(x, j, N, M)
            cons[2*j+1]["jac"] = lambda x: rs_constraint_jacobian(x, j, N, M)


        bounds = []
        for j in range(M+N-1):
            bounds.extend([(None, None)]*4)
            bounds.extend([(-1, 1)]*4)

        opt = scipy.optimize.minimize(objective, self.q, constraints=cons, method="SLSQP", options={"maxiter": 500, "disp": 0, "ftol": 1e-4}, args=(match, self), bounds=bounds)

        self.update_quaternions(opt.x.reshape((N+M-1),2,4))
        return self.squared_distances

    def semi_analytical_solver(self):
        # TODO, remove restraints and do some of the work analytical
        pass

    def update_quarternions(self, q):
        self.q = q.copy()

    def interaction_arrays(self):
        """
        Generate W, Q, Qt_dot_W, W_minus_Q arrays from page 363 Walker91
        disregarding weights (for now)

        """
        # TODO: add ignore hydrogens for calculating the rotations
        W = np.asarray([self.makeW(*x) for x in self.X])#[self.reactant_hydrogen_mask])
        Q = np.asarray([self.makeQ(*y) for y in self.Y])#[self.product_hydrogen_mask])
        Qt_dot_W = np.asarray([[np.dot(q.T,w) for q in Q] for w in W])
        W_minus_Q = np.asarray([[w - q for q in Q] for w in W])
        return W, Q, Qt_dot_W, W_minus_Q

    def makeW(self, r1,r2,r3,r4=0):
        # eqn 16 Walker91
        W = np.asarray([
                 [r4, r3, -r2, r1],
                 [-r3, r4, r1, r2],
                 [r2, -r1, r4, r3],
                 [-r1, -r2, -r3, r4] ])
        return W

    def makeQ(self, r1,r2,r3,r4=0):
        # eqn 15 Walker91
        Q = np.asarray([
                 [r4, -r3, r2, r1],
                 [r3, r4, -r1, r2],
                 [-r2, r1, r4, r3],
                 [-r1, -r2, -r3, r4] ])
        return Q

    def transform(self, r, s):
        Wt_r = self.makeW(*r).T
        Q_r = self.makeQ(*r)
        rot = Wt_r.dot(Q_r)[:3,:3]
        trans = Wt_r.dot(s)[:3]
        return rot, trans


class Atomic(object):
    """
    Atomic(M)

    Atomic matching contribution

    """

    def __init__(self, M):
        self.M = M
        self.score_matrix = self.get_score_matrix()

    def get_score_matrix(self):
        # TODO expand on this

        # the score matrix is created such that a perfect match is 0
        # and imperfect matches are positive
        score_matrix = np.zeros(self.M.match_matrix.shape)

        # sybyl match matrix
        score_matrix += settings.atomic_sybyl_weight * (self.M.reactants_sybyl_types[:, None] != self.M.products_sybyl_types[None,:])

        # enforce that elements only match other elements of same type

        score_matrix += 1e300 * (self.M.reactants_elements[:, None] != self.M.products_elements[None,:])

        return score_matrix

    def score(self, match):
        """
        Return the one bond scoring matrix

        Parameters:
        -----------
        match: array
            match_matrix

        Returns:
        --------
        Score matrix

        """

        # match matrix is only used for rotation, but is included as a parameter for convenience

        return self.score_matrix

class Bond(object):
    """
    Bond(M)

    Bond matching contribution

    """

    def __init__(self, M):
        self.M = M
        self.score_matrix = self.get_score_matrix()

    def get_score_matrix(self):

        reactant_elements = self.M.reaction.reactants.element_symbols
        product_elements = self.M.reaction.products.element_symbols
        reactant_bond_matrix = self.M.reaction.reactants.bond_matrix
        product_bond_matrix = self.M.reaction.products.bond_matrix

        # Construct a matrix function for easy evaluation of the objective
        C = np.zeros(self.M.match_matrix.shape, dtype = object)

        # temporary helper dict to construct the matrix
        pairs = {}

        # fill pairs with all possible bond matches
        for a,b in zip(*np.where(reactant_bond_matrix)):
            element_a, element_b = reactant_elements[[a,b]]
            for i,j in zip(*np.where(product_bond_matrix)):
                element_i, element_j = reactant_elements[[i,j]]
                if (element_a == element_i and element_b == element_j) or (element_a == element_j and element_b == element_i):
                    if (a,i) not in pairs: pairs[(a,i)] = []
                    pairs[a,i].append((b,j))

        # construct the matrix function from the pairs
        for (a,i), container in pairs.items():
            C[a,i] = lambda x: np.sum((x[b,j] for (b,j) in container))
            break
        M = np.random.random(C.shape)
        print M[6,2], M[8,2]
        print C[a,i](M)
        quit()

        # This is Q where Q_ai = sum_bj M_bj * C_aibj
        # find non zero indices for scoring
        w1 = np.where(molP.bonds)
        w2 = np.where(molQ.bonds)
        # weird behavior of itertools.izip, so using zip
        bonds1 = zip(*w1)
        bonds2 = zip(*w2)

        idx_lookup = {}
        for a,b in bonds1:
            for i,j in bonds2:
                if molP.atypes[a] == molQ.atypes[i] and molP.atypes[b] == molQ.atypes[j]:
                    if (a,i) not in idx_lookup: idx_lookup[(a,i)] = []
                    idx_lookup[(a,i)].append((b,j))

        #if has_scipy:
        C = scipy.sparse.dok_matrix((N**2,N**2), dtype=float)
        #else:
        #    C = np.zeros((N**2, N**2), dtype=float)
    
        for (a,i), v in idx_lookup.items():
            for (b,j) in v:
                C[(a*N+i, b*N+j)] = 1
        #if has_scipy:
        C = C.tocsr()
        assert((C!=C.T).nnz == 0)
        #else:
        #    assert(np.allclose(C,C.T))

        #if restrict == "CR":
        #r1 = np.eye(N)-N**(-1) * np.ones((N,N))
        #r2 = r1
        #elif restrict == "C":
        #    r1 = np.eye(N)-N**(-1) * np.ones((N,N))
        #    r2 = np.eye(N)
        #else:
        r1 = np.eye(N)
        r2 = r1

        #if has_scipy:
        R = scipy.sparse.kron(r1,r2) # only with column restriction
        R = ((C.dot(R).T).dot(R.T)).T
        l = scipy.sparse.linalg.eigsh(R, k=1, return_eigenvectors=False, which="SA", tol=1e-4)[0]
        #else:
        #    R = np.kron(r1,r2)
        #    R = ((C.dot(R).T).dot(R.T)).T
        #    l = np.linalg.eigvalsh(R)[0]


        #if add_gamma:
        #gamma = -l + eps_gamma
        #else:
        gamma = 0

        #con = 0
        #for j in range(N):
        #    maxj = 0
        #    for a,b in itertools.product(*([xrange(N)]*2)):
        #        #diff = np.max(C[a*N+i, :] - C[b*N+i,:])
        #        diff = np.max(molP.bonds[a,b]*molQ.bonds*f[a,:,None]*f[b,None,:])
        #        if diff > maxj:
        #            maxj = diff
        #    con += maxj

        #con2 = 0
        #for j in range(molQ.size):
        #    con2 += max(molQ.bonds[:,j].max()*max([molP.bonds[:,c].max() - molP.bonds[:,c].min() for c in range(molP.size)]),
        #                molQ.bonds[:,j].min()*min([molP.bonds[:,c].min() - molP.bonds[:,c].max() for c in range(molP.size)]))
        #assert(con == con2)
    
        con3 = np.sum(np.max(molQ.bonds[None,None,None,:,:]*f[None,None,:,None,:]*(molP.bonds[:,None,:,None,None]*f[:,None,None,:,None]-molP.bonds[None,:,:,None,None]*f[None,:,None,:,None]), axis=(0,1,2,3)))
        con = con3
        #assert(con3 == con)
        #con4 = 0
        #v = (molP.bonds[:,None,:,None]*f[:,None,None,:]-molP.bonds[None,:,:,None]*f[None,:,None,:])[:,:,:,:,None]
        #for j in range(molQ.size):
        #    con4 += np.max(molQ.bonds[None,None,None,:,j]*f[None,None,:,None,j]*v)
    
        #assert(con4 == con)

        # the score matrix is created such that a perfect match is 0
        # and imperfect matches are positive
        score_matrix = np.zeros(self.M.match_matrix.shape)

        # sybyl match matrix
        score_matrix += settings.atomic_sybyl_weight * (self.M.reactants_sybyl_types[:, None] != self.M.products_sybyl_types[None,:])

        # enforce that elements only match other elements of same type

        score_matrix += 1e300 * (self.M.reactants_elements[:, None] != self.M.products_elements[None,:])

        return score_matrix

    def score(self, match):
        """
        Return the one bond scoring matrix

        Parameters:
        -----------
        match: array
            match_matrix

        Returns:
        --------
        Score matrix

        """

        # match matrix is only used for rotation, but is included as a parameter for convenience

        return self.score_matrix

