'''
@File          :  facility.py
@Author        :  Jiang
@Date          :  2022/8/11 下午11:02 
@Description   :  
'''
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from matplotlib import rcParams
from matplotlib.colors import LogNorm, Normalize
import math
import seaborn as sns
import time
import os
import datetime
import imageio
import multiprocessing
import json


today = str(datetime.date.today())[5:]  # 日期戳
# 设置字体，仿宋：FangSong，黑体：SimHei，宋体：SimSun，微软雅黑：Microsoft YaHei
matplotlib.rc("font", family='Microsoft YaHei ')
matplotlib.rcParams['xtick.direction'] = 'in'  # 刻度标签方向：in, out
matplotlib.rcParams['ytick.direction'] = 'in'

# REF_POINTS_SET = [3, 3, 3]
CROSS_LENGTH = 8
DOSE_CAL_STEP_LENGTH = 2  # 取点的间隔为 2cm，据此得出每个步长点位上货箱停留时长，进而得出累积剂量
SPEED = 200  # 传送带速度，200cm/min

# 计算单点的吸收剂量，Gy
# (xi,yi,zi) 为参考面上坐标，棒坐标(x_0, y_0)取 (0,bar_length / 2)
def cal_dose(activity, bar_length, x_0, y_0, x_i, y_i, z_i):
    # Co-60照射量率常数,2.503e-18 C.m2/(kg.bq.s)
    constant = 2.503e-14  # C.cm2/(kg.bq.s)
    source_activity = activity * 3.7e10  # Ci to Bq, activity单位为居里
    da = np.sqrt((x_i - x_0) ** 2 + z_i ** 2)
    db = y_i - y_0
    # 照射量
    exposure = constant*source_activity*(np.arctan((bar_length + db) / da) - np.arctan(db / da)) / (da * bar_length)
    ab_dose_rate = 33.85 * exposure * 60
    # 吸收剂量率，Gy/min
    # 根据步长，计算出，货箱在单个移动步长上的，吸收剂量值 Gy
    ab_dose = ab_dose_rate * DOSE_CAL_STEP_LENGTH/SPEED
    return ab_dose  # numpy数组

#  用以计算排源方案的剂量场
# bar_length = 45
# bar_radius = 1 / 2

class Facility(object):
    def __init__(self, facility_info):
        # 读取配置json文件
        self.cfg = self.read_config(file=facility_info)
        self.name = self.cfg["facility"]["name"]
        self.type = self.cfg["facility"]["type"]
        self.work_dir = self.name + "_" + str(today)
        # 棒位相关
        self.pos_xy, self.positions = self.get_bar_positions_xy()
        # 源棒相关参数
        self.bars = self.cfg["source pencils"]["number"]
        self.bar_length = self.cfg["source pencils"]["bar_length"]
        self.bar_radius = self.cfg["source pencils"]["bar_radius"]
        self.bar_activity = self.cfg["source pencils"]["activity"]
        # 货箱内剂量参考点
        self.ref_points = self.get_ref_points_xyz()
        self.ref_points_set = self.cfg["product cage"]["reference_dose_point_set"]
        print(" class Facility __init__ has been called.. ")
        # 所有棒位在27个参考点上的累积剂量和
        self.ref_dose = self.get_ref_doses()

    @staticmethod
    def read_config(file):
        with open(file, 'r') as f:
            config_data = json.load(f)
        return config_data

    def get_bar_positions_xy(self):  # 得出的棒位坐标，以其 上 端点为准
        # 源板相关参数，目的：计算得出所有可用棒位的坐标（上端点）
        modules_set = self.cfg["source rack"]["modules_set"]
        modules_x_intervals = self.cfg["source rack"]["modules_x_intervals"]
        modules_y_intervals = self.cfg["source rack"]["modules_y_intervals"]
        module_position = self.cfg["source rack"]["module_position"]
        interval = self.cfg["source rack"]["source_interval"]
        #
        modules_number = modules_set[0] * modules_set[1]
        bar_positions_number = modules_number * module_position
        # 包含所用棒位信息的df，列数为棒位总数，行数为2(x,y)
        pos_xy_df = pd.DataFrame(columns=['x', 'y'], index=np.arange(1, bar_positions_number + 1, 1))
        # ## 得出每行棒位的x坐标
        x_1 = np.arange(0, modules_set[0] * module_position * interval, interval)  # 59
        # 插入源板之间的间距：得出由于源板横向间距产生的x坐标位置增加量
        x_2 = x_1
        if modules_set[0] != 1:  # 每行有两块源板时，才加上源板间隔
            x_add = [0]
            dx = [_ - interval for _ in modules_x_intervals]  # 扣除固定棒间距
            for i in range(0, len(modules_x_intervals)):
                x_add.append(sum(dx[:i + 1]))
            x_add_re = np.asarray([var for var in x_add for j in range(module_position)])
            x_2 = x_1 + x_add_re
        # x坐标恢复为中心对称
        x_3 = [_ - x_2[-1] / 2 for _ in x_2]
        # 按照单行的x坐标，扩充到所有棒位上，重复 源板的行数
        pos_xy_df.iloc[:, 0] = list(x_3) * modules_set[1]  # 59*4
        # ## 计算y坐标
        y_1 = np.arange(0, modules_set[1] * self.bar_length, self.bar_length)  # 4
        y_add = [0]
        for i in range(0, len(modules_y_intervals)):
            y_add.append(sum(modules_y_intervals[:i + 1]))
        y_2 = np.asarray(y_1) + np.asarray(y_add)
        # y坐标恢复为中心对称
        y_3 = [_ - (y_2.max() + self.bar_length) / 2 + self.bar_length for _ in y_2]
        # y方向上源棒位置先后顺序为从上到下，因此需颠倒每层的
        y_3.reverse()
        # 按照单列的y坐标，扩充到所有棒位上，重复 每行上的棒位数目
        pos_xy_df.iloc[:, 1] = np.repeat(y_3, module_position * modules_set[0])  # 4*59
        return pos_xy_df, bar_positions_number

    def get_ref_points_xyz(self):  # 待计算的剂量参考点坐标
        # 从货箱信息文件中读取参数
        cage_x = self.cfg["product cage"]["cage_width"]  # 93.0cm
        cage_y = self.cfg["product cage"]["cage_height"]  # 154.0 cm
        cage_z = self.cfg["product cage"]["cage_thickness"]  # 57.0 cm
        cage_away_rack = self.cfg["product cage"]["cage_from_rack"]  # 31.5 cm
        cage_layers = self.cfg["product cage"]["cage_layers"]  # 2 layers
        cage_each_layer = self.cfg["product cage"]["cage_each_layer"]  # 8 cage each layer
        cage_dx = self.cfg["product cage"]["distance_between_cages"]  # distance_between_cages 2 cm
        cage_dy = self.cfg["product cage"]["distance_between_layers"]  # distance_between_layers 18.2、
        # ref_points_set = self.cfg["product cage"]["reference_dose_point_set"]
        # 计算一些间接的参数
        cage_step = cage_x + cage_dx  # 95 cm
        cages = cage_layers*cage_each_layer  # one side, total cages, 16
        x_max = 0.5*cage_each_layer*cage_step-0.5*cage_dx  # x max of the cage, it is 379cm
        y_max = 0.5*cage_dy + cage_y
        # 开始计算参考剂量点的坐标
        x_step_size = DOSE_CAL_STEP_LENGTH  # 步长2cm，-379~379，一共379个点
        x_dots = np.arange(x_max, -x_max - x_step_size, -x_step_size)  # 完整流程需要重复四次
        x_dots_repeat = np.hstack([x_dots, x_dots, x_dots, x_dots])  # 完整流程需要重复四次
        ref_dose_pos = np.zeros(self.ref_points_set + [3, len(x_dots) * 4])
        for k in range(self.ref_points_set[2]):  # z方向剂量点
            for j in range(self.ref_points_set[1]):  # y方向剂量点
                for i in range(self.ref_points_set[0]):  # x方向剂量点
                    # x方向坐标，保持固定的序列不改变
                    ref_dose_pos[i, j, k, 0] = x_dots_repeat
                    # y方向坐标，随着j值变化
                    temp_y = np.asarray([y_max - 0.5 * cage_y * j, -y_max + 0.5 * cage_y * (2 - j)])
                    ref_dose_pos[i, j, k, 1] = temp_y.repeat(len(x_dots) * 2)
                    temp_z = np.asarray([cage_away_rack + 0.5 * cage_z * k, cage_away_rack + 0.5 * cage_z * (2 - k)])
                    ref_dose_pos[i, j, k, 2] = np.append(temp_z, temp_z).repeat(len(x_dots))
        return ref_dose_pos

    def get_ref_doses(self):  # 所有棒位在27个参考点上的累积剂量和
        std_dose = np.zeros([self.positions, self.ref_points_set[0], self.ref_points_set[1], self.ref_points_set[2]])
        # 分别算出，单位活度的源棒在236个棒位上对 27 个参考点的累积剂量 【236,3,3,3】
        for pos in range(self.positions):
            temp_dose = np.zeros(self.ref_points_set)
            for k in range(self.ref_points_set[2]):  # z方向
                for j in range(self.ref_points_set[1]):  # y方向
                    for i in range(self.ref_points_set[0]):  # x方向
                        # 计算出 单个 参考点， 经过换面、换层操作后的累积剂量
                        temp_dose[i, j, k] = cal_dose(activity=1, bar_length=self.bar_length,
                                                      x_0=self.pos_xy.iloc[pos, 0], y_0=self.pos_xy.iloc[pos, 1],
                                                      x_i=self.ref_points[i, j, k, 0],  # x方向坐标序列
                                                      y_i=self.ref_points[i, j, k, 1],  # y方向坐标序列
                                                      z_i=self.ref_points[i, j, k, 2]).sum()
            std_dose[pos] = temp_dose
        # np.save('./docs/' + self.work_dir + '/' + self.name + '_ref_points_std_dose.npy', std_dose)
        return std_dose


class Plan(Facility):
    """
    排源方案：继承自Facility
    属性：方案表示（DNA、个体）、UDR、AvgD、货笼剂量点数据
    方法：计算UDR、AvgD
    """
    # def __init__(self, pos_dose, activity_list):
    #     self.pos_dose = pos_dose
    #     self.activity = activity_list
    #     self.bars = len(activity_list)

    def get_random_plan(self, plans=200):
        return np.vstack([np.random.permutation(self.positions)[np.random.permutation(self.bars)]
                          for _ in range(plans)]) + 1

    def get_plan_doses(self):  # 参考点累积剂量分布
        return

    def get_evaluates(self):  # 根据参考点累积剂量，得出评估：DUR、AvgD
        return

    def draw(self):
        return


if __name__ == '__main__':
    f1 = Facility(facility_info='../hengde.json')

    print("ok")