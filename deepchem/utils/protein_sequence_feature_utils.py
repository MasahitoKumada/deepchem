# -*- coding: utf-8 -*-
"""
Created on Sun Oct 11 23:31:45 2020

@author: Zhenqin Wu
"""
import os
import numpy as np
from deepchem.utils.amino_acid_utils import AminoAcid, AminoAcidFreq, BLOSUM62, ContactPotential
from scipy.spatial.distance import pdist, squareform


def amino_acid_to_numeric(s):
  if s in AminoAcid:
    return AminoAcid[s]
  else:
    return AminoAcid['X']


def read_a3m_as_mat(sequence, a3m_seq_IDs, a3m_seqs, clean=True):
  """ Read .a3m profile generated by hhblits """
  assert sequence == a3m_seqs[0]
  sequence_array = [amino_acid_to_numeric(s) for s in sequence]
  seq_len = len(sequence_array)
  seq_mat = []
  for seq in a3m_seqs:
    seq_arr = [amino_acid_to_numeric(s) for s in seq if not s.islower()]
    if clean and sequence_identity(sequence_array, seq_arr) < seq_len * 0.01:
      continue
    seq_mat.append(seq_arr)
  seq_mat = np.array(seq_mat).astype(int)
  return seq_mat


def sequence_one_hot_encoding(sequence):
  """ One-hot encoding of amino acid sequence """
  for s in sequence:
    if not s == '-' and not s.isalpha():
      raise ValueError('Sequence %s not recognized' % sequence)
  seq_one_hot = np.zeros((len(sequence), len(AminoAcid)))
  for i, s in enumerate(sequence):
    seq_one_hot[i, amino_acid_to_numeric(s)] = 1
  return seq_one_hot


def sequence_deletion_probability(sequence, a3m_seqs):
  deletion_matrix = []
  for msa_sequence in a3m_seqs:
    deletion_vec = []
    deletion_count = 0
    for j in msa_sequence:
      if j.islower():
        deletion_count += 1
      else:
        deletion_vec.append(deletion_count)
        deletion_count = 0
    deletion_matrix.append(deletion_vec)
  deletion_matrix = np.array(deletion_matrix)
  deletion_matrix[deletion_matrix != 0] = 1.0
  deletion_probability = deletion_matrix.sum(0)/len(deletion_matrix)
  return deletion_probability.reshape((len(sequence), 1))


def sequence_weights(seq_mat):
  n_align, n_res = seq_mat.shape  
  dist_mat = pdist(seq_mat, 'hamming')
  dist_mat = squareform(dist_mat < 0.38)
  weights = 1 + np.sum(dist_mat, 0)
  return (1.0 / weights).reshape((n_align, 1))


def sequence_profile(seq_mat, weights=None):
  prof_ct = np.zeros((seq_mat.shape[1], 22))
  if weights is None:
    weights = np.ones((seq_mat.shape[0], 1))
  for i in range(22):
    prof_ct[:, i] = ((seq_mat == i) * weights).sum(0)
  prof_freq = prof_ct/prof_ct.sum(1, keepdims=True)
  return prof_freq


def sequence_profile_no_gap(seq_mat, weights=None):
  prof_ct = np.zeros((seq_mat.shape[1], 21))
  for i in range(21):
    prof_ct[:, i] = (seq_mat == i).sum(0)
  prof_freq = prof_ct/prof_ct.sum(1, keepdims=True)
  return prof_freq


def sequence_profile_with_prior(prof_freq):
  out_freq = np.zeros_like(prof_freq)
  beta = 10
  P_i = [AminoAcidFreq[aa] for aa in \
      sorted(AminoAcid.keys(), key=lambda x: AminoAcid[x])]
  P_i = P_i[:prof_freq.shape[1]]
  P_i = np.array(P_i)/sum(P_i)
  substitution_mat = BLOSUM62[:prof_freq.shape[1], :prof_freq.shape[1]]
  q_mat = np.matmul(P_i.reshape((-1, 1)), P_i.reshape((1, -1))) * \
      np.exp(0.3176 * substitution_mat)
  for i in range(len(prof_freq)):
    f_i = prof_freq[i]
    NC = np.where(f_i > 0)[0].shape[0]
    alpha = NC - 1
    g_i = np.matmul((f_i/P_i).reshape((1, -1)), q_mat)[0]
    g_i = g_i/g_i.sum()
    out_freq[i] = (f_i * alpha + g_i * beta)/(alpha + beta)
  return out_freq
    
  
def sequence_identity(s1, s2):
  s1 = np.array(s1)
  s2 = np.array(s2)
  return ((s1 == s2) * (s1 != AminoAcid['-'])).sum()


def sequence_static_prop(seq_mat, weights):
  num_alignments, seq_length = seq_mat.shape
  num_effective_alignments = weights.sum()
  feat = np.array([seq_length, num_alignments, num_effective_alignments])
  feat = np.stack([feat] * seq_length, 0)
  feat = np.concatenate([np.arange(seq_length).reshape((-1, 1)), feat], 1)
  return feat


def sequence_gap_matrix(seq_mat):
  gaps = (seq_mat == AminoAcid['-']) * 1
  gap_matrix = np.matmul(np.transpose(gaps), gaps) / seq_mat.shape[0]
  return gap_matrix


def profile_combinatorial(seq_mat, weights, w_prof):
  M, N = seq_mat.shape
  n_res = w_prof.shape[1]
  w = weights.reshape((M, 1, 1))
  combined = seq_mat.reshape((M, N, 1)) * 22 + seq_mat.reshape((M, 1, N))
  prof_2D = np.zeros((N, N, n_res, n_res))
  for i in range(n_res):
    for j in range(n_res):
      prof_2D[:, :, i, j] = ((combined == (i * 22 + j)) * w).sum(0)
  prof_2D = prof_2D / np.sum(w)
  return prof_2D


def mutual_information(prof_1D, prof_2D):
  """ This series of properties were calculated based on:
    "Mutual information without the influence of phylogeny or entropy
     dramatically improves residue contact prediction"
  """
  n_res = prof_1D.shape[0]
  def no_diag(mat):
    return 2 * mat - np.triu(mat) - np.tril(mat)
  H_1D = np.sum(-prof_1D * np.log(prof_1D + 1e-7) / np.log(21), axis=1)
  H_2D = np.sum(-prof_2D * np.log(prof_2D + 1e-7) / np.log(21), axis=(2, 3))
  MI = -H_2D + H_1D.reshape((n_res, 1)) + H_1D.reshape((1, n_res))  
  # Only take off-diagonal parts
  MI = no_diag(MI)
  MIr = MI / (H_2D + 1e-5)
  
  MI_1D = np.sum(MI, axis=1)/(n_res-1)
  MI_av = np.sum(MI)/n_res/(n_res-1)
  APC = MI_1D.reshape((n_res, 1)) * MI_1D.reshape((1, n_res)) / MI_av
  ASC = MI_1D.reshape((n_res, 1)) + MI_1D.reshape((1, n_res)) - MI_av  
  MIp = no_diag(MI - APC)
  MIa = no_diag(MI - ASC)  
  MI_feats = np.stack([MI, MIr, MIp, MIa], 2)
  return MI_feats


def mean_contact_potential(prof_2D):
  n_res = prof_2D.shape[2]
  cp = ContactPotential[:n_res, :n_res]
  mcp = np.sum(prof_2D * cp.reshape((1, 1, n_res, n_res)), axis=(2, 3))
  return np.expand_dims(mcp, 2)