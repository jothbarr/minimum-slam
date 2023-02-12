'''
playground for testing GTSAM
'''
import os
import gtsam
import numpy as np
from scipy.spatial.transform import Rotation as R
from gtsam.symbol_shorthand import L, X
import matplotlib.pyplot as plt
from frontend_evaluate import FrontendEvaluate
import math
import matplotlib
from dataclasses import dataclass

matplotlib.use('TkAgg')

@dataclass
class ProjectionFactor:
    landmark_id: int
    smart_factor: gtsam.SmartProjectionPose3Factor
    slot: int = -1
    gt: np.array = np.ones(3)
    estimated: np.array = np.ones(3)

class GTSAM_Backend():

    def __init__(self, verbose='debug', log_file=None):
        # setup canvas
        fig, axs = plt.subplots(ncols=2, subplot_kw=dict(projection="3d"))
        for ax in axs:
            ax.view_init(23,-150)
        self.axs = axs
        # plt.ion()
        # graph
        self.factors = {}
        self.graph = gtsam.NonlinearFactorGraph()
        self.verbose = verbose
        self.log_file = log_file

    def set_frontend(self, frontend):
        self.frontend = frontend

    def print(self, level='log', *values):
        if level=='log' or level=='debug' and self.verbose=='debug':
            print(*values)

    def optimize(self, factor_type='mixed', optimizer='LM', max_factor_error=10):
        # graph
        initial_estimate = gtsam.Values()

        # factors
        smart_factor_params = gtsam.SmartProjectionParams()
        smart_factor_params.setDegeneracyMode(gtsam.DegeneracyMode.ZERO_ON_DEGENERACY) #HANDLE_INFINITY ZERO_ON_DEGENERACY
        smart_factor_params.setRankTolerance(1)
        # smart_factor_params.setLandmarkDistanceThreshold(100)
        # smart_factor_params.setDynamicOutlierRejectionThreshold(10000)

        # camera and noise
        fx, fy, cx, cy = self.frontend.camera
        K = gtsam.Cal3_S2(fx, fy, 0.0, cx, cy)
        uv_measurement_noise = gtsam.noiseModel.Isotropic.Sigma(2, 1)
        uv_measurement_noise_robust = gtsam.noiseModel.Robust.Create(gtsam.noiseModel.mEstimator.Huber.Create(1.345), uv_measurement_noise)
        landmark_prior_noise = gtsam.noiseModel.Isotropic.Sigma(3, 1)
        first_pose_prior_noise = gtsam.noiseModel.Diagonal.Sigmas(np.ones(6)*0.001)

        pose_prior_noise = gtsam.noiseModel.Diagonal.Sigmas(
            np.array([10*math.pi/180]*3+[0.1]*3)
        )
        camera_pose = gtsam.Pose3(
            gtsam.Rot3(self.frontend.cameraPose.rotation),
            gtsam.Point3(self.frontend.cameraPose.translation.flatten())
        )

        # debug
        count = [0]*10
        first_frame_id = next(iter(self.frontend.frames))
        landmark_set = set()

        # create projection factors
        for frame_id, curr_frame in self.frontend.frames.items():
            self.print('debug', f'=========== FRAME {frame_id} ===========')
            pose = gtsam.Pose3(
                gtsam.Rot3(curr_frame.rotation),
                gtsam.Point3(curr_frame.translation.flatten())
            )
            initial_estimate.insert(X(frame_id), pose)
            if frame_id==first_frame_id:
                self.graph.push_back(gtsam.PriorFactorPose3(
                    X(frame_id), pose, first_pose_prior_noise
                ))
            elif frame_id<=first_frame_id+3:
                self.graph.push_back(gtsam.PriorFactorPose3(
                    X(frame_id), pose, pose_prior_noise
                ))
            for landmark_id in curr_frame.observed_landmark_id:
                landmark = self.frontend.landmarks[landmark_id]
                if factor_type=='smart':
                    if landmark.frames[0]==frame_id:
                        factor = gtsam.SmartProjectionPose3Factor(uv_measurement_noise, K, camera_pose, smart_factor_params)
                        self.factors[landmark_id] = ProjectionFactor(landmark_id, factor)
                    else:
                        factor = self.factors[landmark_id].smart_factor
                    factor.add(np.array(landmark.uv[frame_id]), X(frame_id))
                    if landmark.frames[-1]==frame_id:
                        # self.print('debug', len(landmark.uv), factor.size())
                        try:
                            # factor.print()
                            error = factor.error(initial_estimate)
                        except:
                            self.print('debug', 'Failed when calculating error')
                            continue
                        if factor.size()>=2:
                            count[0] += 1
                            if frame_id in landmark.gt_xyz:
                                gt_point = landmark.gt_xyz[frame_id].flatten()
                            else:
                                gt_point = None
                            self.factors[landmark_id].gt = gt_point
                        if factor.size()>=2 and error==0:
                            status = factor.getStatus()
                            if status!=2:
                                self.print('debug', f'Triangulation failed. Status={status}')
                            count[1] += 1
                        if factor.size()>=2 and error>0:
                            estimated_point = factor.getPoint()
                            self.factors[landmark_id].estimated = estimated_point
                            if gt_point is not None:
                                error_gt = np.linalg.norm(gt_point-estimated_point)
                            else:
                                error_gt = -1
                            count[2] += 1
                        if factor.size()>=2 and error/len(landmark.uv)<max_factor_error:
                            count[4] += 1
                        # if frame_id==45 and factor.size()>=2:
                        if factor.size()>=2 and error>0 and error/len(landmark.uv)<max_factor_error:
                            # if frame_id==38:
                                # self.frontend.show_matches('test', list(landmark.uv.keys()), [list(landmark.uv.values())], -1)
                            #     print(landmark_id, end=', ')
                            #     # factor.print()
                            #     # factor.printPoint()
                                # if error_gt>5:
                                #     continue
                                # if landmark_id in [4620,5148,4543]:
                                #     continue
                                # self.print('log', 'result: ',landmark_id, gt_point, estimated_point, error_gt, error/len(landmark.uv), len(landmark.uv))

                            count[3] += 1
                            self.graph.push_back(factor)
                            for x in landmark.uv.keys():
                                landmark_set.add(x)
                            # factor.print()
                            # self.print('debug', f'size: {factor.size()}, error: {error}, average error: {error/factor.size()}')
                            # self.print('debug', '==========')
                        # self.print('debug', f'added!')
                elif factor_type=='generic':
                    if landmark.frames[0]==frame_id:
                        initial_estimate.insert(L(landmark_id), gtsam.Point3(*landmark.xyz[frame_id]))
                        self.graph.push_back(gtsam.PriorFactorPoint3(
                            L(landmark_id), gtsam.Point3(*landmark.xyz[frame_id]), landmark_prior_noise
                        ))
                    self.graph.push_back(gtsam.GenericProjectionFactorCal3_S2(
                        np.array(landmark.uv[frame_id]), uv_measurement_noise_robust, X(frame_id),
                        L(landmark_id), K, camera_pose
                    ))
                elif factor_type=='mixed':
                    if landmark.frames[0]==frame_id:
                        # add prior to the landmark if it's the first measurement
                        smart_factor = gtsam.SmartProjectionPose3Factor(uv_measurement_noise, K, camera_pose, smart_factor_params)
                        self.factors[landmark_id] = ProjectionFactor(landmark_id, smart_factor)
                    else:
                        # otherwise find the existing factor
                        smart_factor = self.factors[landmark_id].smart_factor
                    # add the measurement to the factor
                    smart_factor.add(np.array(landmark.uv[frame_id]), X(frame_id))
                    # skip the rest if measurements are not enough
                    if smart_factor.size()<2:
                        continue
                    # get the triangulation result
                    try:
                        # factor.print()
                        error = smart_factor.error(initial_estimate)
                        status = smart_factor.getStatus()
                    except:
                        self.print('debug', 'Failed when calculating error')
                        continue
                    if status>0:
                        self.print('debug', f'Failed when calculating error, landmark_id={landmark_id}, status={status}')
                        continue
                    if error/len(landmark.uv)>max_factor_error:
                        self.print('debug', f'Failed due to large error, landmark_id={landmark_id}, status={status}')
                        continue
                    # if landmark.frames[0]==frame_id:
                    if not initial_estimate.exists(L(landmark_id)):
                        initial_estimate.insert(L(landmark_id), gtsam.Point3(*landmark.xyz[frame_id]))
                        self.graph.push_back(gtsam.PriorFactorPoint3(
                            L(landmark_id), gtsam.Point3(*landmark.xyz[frame_id]), landmark_prior_noise
                        ))
                    self.graph.push_back(gtsam.GenericProjectionFactorCal3_S2(
                        np.array(landmark.uv[frame_id]), uv_measurement_noise_robust, X(frame_id),
                        L(landmark_id), K, camera_pose
                    ))
        # for i in range(landmark.frames[-1]+1):
        #     if not i in landmark_set:
        #         self.print('log', f'frame {i} has no measurement')

        # debug
        self.print('log', f'count: {count}')

        # optimize the graph
        self._optimize(initial_estimate, optimizer)

        # plot
        self.plot(0, block=False, timeout=0.1)

        # filter factors
        if factor_type=='smart':
            for i in range(3):
                self.print('log', f'=== Re-optimization {i+1} ===')
                self.graph = gtsam.NonlinearFactorGraph()
                for landmark_id, factor in self.factors.items():
                    measurement_size = factor.smart_factor.size()
                    if measurement_size<2:
                        continue
                    error = factor.smart_factor.error(self.current_estimate)
                    estimated_point = factor.smart_factor.getPoint()
                    if factor.gt is not None:
                        previous_error = np.linalg.norm(factor.gt-self.factors[landmark_id].estimated)
                        error_gt = np.linalg.norm(factor.gt-estimated_point)
                    else:
                        previous_error = -1
                        error_gt = -1
                    # if landmark_id in [5318, 5317, 5316, 5307, 100, 5284, 4543, 5321, 5017, 4, 3216, 4620, 5142, 5148, 44]:
                        # self.print('log', 'result: ', landmark_id, factor.gt, estimated_point, error, previous_error, error_gt)
                    if error>0 and error/len(landmark.uv)<1500: #2500
                        self.graph.push_back(factor.smart_factor)
                pose = self.current_estimate.atPose3(X(first_frame_id))
                self.graph.push_back(gtsam.PriorFactorPose3(
                    X(first_frame_id), pose, first_pose_prior_noise
                ))
                self._optimize(self.current_estimate, optimizer)

        # plot
        self.plot(1, block=False)
        plt.show(block=True)
        plt.pause(1)

    def _optimize(self, initial_estimate, optimizer):
        self.print('log', 'graph.size(): ', self.graph.size())
        self.print('log', 'before optimizaiton error(): ', self.graph.error(initial_estimate))

        if optimizer=='LM':
            optimizer_params = gtsam.LevenbergMarquardtParams()
            optimizer_params = gtsam.LevenbergMarquardtParams.CeresDefaults()
            # optimizer_params.setVerbosityLM('SUMMARY')
            optimizer = gtsam.LevenbergMarquardtOptimizer(self.graph, initial_estimate, optimizer_params)
            current_estimate = optimizer.optimize()
        elif optimizer=='GN':
            optimizer = gtsam.GaussNewtonOptimizer(self.graph, initial_estimate)
            current_estimate = optimizer.optimize()
        elif optimizer=='ISAM2':
            optimization_params = gtsam.ISAM2DoglegParams()
            optimization_params.setVerbose(True)
            optimizer_params = gtsam.ISAM2Params()
            optimizer_params.setRelinearizeThreshold(0.001)
            optimizer_params.setOptimizationParams(optimization_params)
            optimizer = gtsam.ISAM2(optimizer_params)
            optimizer.update(self.graph, initial_estimate)
            current_estimate = optimizer.calculateEstimate()

        self.current_estimate = current_estimate    
        self.print('log', 'after optimizaiton error(): ', self.graph.error(self.current_estimate))
    
    def save_estimated_traj(self, output_file, gt_file):
        output = open(output_file, 'w')
        for frame_id, curr_frame in self.frontend.frames.items():
            pose = self.current_estimate.atPose3(X(frame_id))
            pos = pose.translation()
            rot = pose.rotation().matrix()
            quad = R.from_matrix(rot).as_quat()
            data = [frame_id, *pos, *quad]
            output.write(' '.join([str(x) for x in data])+'\n')
        output = open(gt_file, 'w')
        for frame_id, curr_frame in self.frontend.frames.items():
            pose = self.current_estimate.atPose3(X(frame_id))
            pos = curr_frame.gt_translation.flatten()
            rot = curr_frame.gt_rotation
            quad = R.from_matrix(rot).as_quat()
            data = [frame_id, *pos, *quad]
            output.write(' '.join([str(x) for x in data])+'\n')

    def plot(self, subplot_index=0, block=False, timeout=0.1, plot_input_traj=True, plot_estimated_traj=True, plot_gt_traj=True):
        ax = self.axs[subplot_index]
        ax.clear()
        ax.set_xlabel('x')
        ax.set_ylabel('y')
        ax.set_zlabel('z')
        # ax.set_xlim3d(-10, 10)
        # ax.set_ylim3d(-10, 10)
        # ax.set_zlim3d(-10, 10)
        first_id = next(iter(self.frontend.frames))

        # plot input_traj
        if plot_input_traj:
            traj = np.zeros([3, len(self.frontend.frames)])
            for frame_id, curr_frame in self.frontend.frames.items():
                offset = frame_id-first_id
                traj[:, offset] = curr_frame.translation.flatten()
            ax.plot3D(traj[0,:], traj[1,:], traj[2,:]+0.01, 'blue', label='input')

        # plot gt_traj
        if plot_gt_traj:
            traj = np.zeros([3, len(self.frontend.frames)])
            for frame_id, curr_frame in self.frontend.frames.items():
                offset = frame_id-first_id
                traj[:, offset] = curr_frame.gt_translation.flatten()
            ax.plot3D(traj[0,:], traj[1,:], traj[2,:], 'orange', label='ground truth')

        # plot estimated_traj
        if plot_estimated_traj:
            traj = np.zeros([3, len(self.frontend.frames)])
            for frame_id, curr_frame in self.frontend.frames.items():
                offset = frame_id-first_id
                traj[:, offset] = self.current_estimate.atPose3(X(frame_id)).translation()
                # ax.text(traj[0,offset], traj[1,offset], traj[2,offset], frame_id)
            ax.plot3D(traj[0,:], traj[1,:], traj[2,:], 'red', label='estimated')

        # show the plot
        ax.legend()
        # plt.show(
        #     block=block
        # )
        self.print('debug', 'block: ',block)
        # plt.pause(timeout)
    
    def write_factor_log_header(self):
        factor_log = open(self.log_file, 'w')
        column_names = ['factor_type', 'id', 'error', 'label']
        factor_log.write(','.join(column_names))
    
    def evaluate(self):
        error_input = 0
        error_estimated = 0
        traj_input = np.ones([len(self.frontend.frames), 3])
        traj_gt = np.ones([len(self.frontend.frames), 3])
        traj_estimated = np.ones([len(self.frontend.frames), 3])
        first_id = next(iter(self.frontend.frames))
        for frame_id, curr_frame in self.frontend.frames.items():
            offset = frame_id-first_id
            pos_input = curr_frame.translation.flatten()
            pos_gt = curr_frame.gt_translation.flatten()
            pos_estimated = self.current_estimate.atPose3(X(frame_id)).translation()
            error_input += np.linalg.norm(pos_input-pos_gt)
            error_estimated += np.linalg.norm(pos_estimated-pos_gt)
        print('error_input: ', error_input)
        print('error_estimated: ', error_estimated)


if __name__ == '__main__':
    dataset_type = 'tartanair'
    dataset_scene = 'seasidetown' #oldtown
    dataset_folder = os.path.expanduser(f'~/Projects/curly_slam/data/tartanair/scenes/{dataset_scene}/Easy/P000')
    frontend_file = os.path.expanduser(f'~/Projects/curly_slam/data/curly_frontend/curly_tartanair_{dataset_scene}.txt')
    dataset_path = {
        'depth': dataset_folder+'/depth_image',
        'color': dataset_folder+'/image_left',
        'frontend': frontend_file,
        'gt_traj': dataset_folder+'/pose_left.txt',
        'odom_traj': dataset_folder+'/pose_left.txt', #cvo_pose_transformed.txt'
        # 'odom_traj': dataset_folder+'/pose_left_noisy.txt', #cvo_pose_transformed.txt'
    }
    frontend = FrontendEvaluate(dataset_type, dataset_path)
    backend = GTSAM_Backend(verbose='debug', log_file='log/backend.csv')
    for i in range(50,51,1): #727
        print(f'===== FRAME LENGTH {i} =====')
        frontend.load_dataset(start=0, end=i, align_start_point=False)
        frontend.calc_xyz_locally()
        frontend.get_ground_truth_match()
        frontend.evaluate(viz_matches=False)
        backend.set_frontend(frontend)
        # backend.plot(0,True, 100, True, False, True)
        # plt.show(block=True)
        backend.optimize(factor_type='smart', optimizer='LM', max_factor_error=1000)
        backend.evaluate()
        backend.save_estimated_traj(dataset_folder+'/pose_left_estimated.tum', dataset_folder+'/pose_left_gt.tum')
    print("EOF")