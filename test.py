import os
import argparse
import tensorflow as tf

from src.config import Config
from src.judger import Judger

parser = argparse.ArgumentParser()
parser.add_argument('--model', '-m')
args = parser.parse_args()

current_model = args.model
config = Config('./', current_model)

print('Current model: ', config.current_model)
if config.current_model == 'fasttext':
    from src.test.test_fasttext import test
elif config.current_model == 'bilstm':
    from src.test.test_bilstm import test
elif config.current_model == 'bigru':
    from src.test.test_bigru import test
elif config.current_model == 'han':
    from src.test.test_han import test
elif config.current_model == 'cnn':
    from src.test.test_cnn import test
elif config.current_model == 'dpcnn':
    from src.test.test_dpcnn import test
elif config.current_model == 'topjudge':
    from src.test.test_topjudge import test
elif config.current_model == 'fact_law':
    from src.test.test_fact_law import test
elif config.current_model == 'law_att':
    from src.test.test_law_att import test
else:
    print('No model named: ', config.current_model)
    exit()

os.environ['CUDA_VISIBLE_DEVICES'] = '0'
config_proto = tf.ConfigProto(allow_soft_placement=True)  # 创建配置，允许将无法放入GPU的操作放在CUP上执行
config_proto.gpu_options.allow_growth = True  # 运行时动态增加内存使用量
judger = Judger(config.accu_dict, config.law_dict)

test(config, judger, config_proto)