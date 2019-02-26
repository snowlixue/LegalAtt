import codecs
import json
import os
import random
import time
import numpy as np
import tensorflow as tf
from sklearn.externals import joblib

from src import config
from src import util
from src.model import FactLaw


def pad_fact_batch(fact_batch):
    new_batch = []
    for fact in fact_batch:
        temp = [[config.PAD_ID] * config.SEQUENCE_LEN] * config.DOCUMENT_LEN
        for i in range(len(fact)):
            temp[i][:len(fact[i])] = fact[i]
        new_batch.append(temp)
    return new_batch


def pad_law_kb(law_kb):
    new_law_kb = []
    for art in law_kb:
        temp = [[config.PAD_ID] * config.SEQUENCE_LEN] * config.DOCUMENT_LEN
        for i in range(len(art)):
            temp[i][:len(art[i])] = art[i]
        new_law_kb.append(temp)
    return new_law_kb


def inference(sess, model, batch_iter, kb_data, out_file, verbose=True):
    law_kb, law_seq_len, law_doc_len = kb_data

    task_1_output = []
    task_2_output = []
    task_3_output = []
    start_time = time.time()
    for i, batch in enumerate(batch_iter):
        if verbose:
            print('processing batch: %5d' % i, end='\r')

        fact, fact_seq_len, fact_doc_len, tfidf = list(zip(*batch))

        batch_size = len(fact)
        fact = pad_fact_batch(fact)

        feed_dict = {
            model.fact: fact,
            model.fact_seq_len: fact_seq_len,
            model.fact_doc_len: fact_doc_len,
            model.tfidf: tfidf,
            model.law_kb: [law_kb] * batch_size,
            model.law_seq_len: [law_seq_len] * batch_size,
            model.law_doc_len: [law_doc_len] * batch_size
        }

        _task_1_output = sess.run(
            model.task_1_output,
            feed_dict=feed_dict
        )
        task_1_output.extend(_task_1_output)
        task_2_output.extend([[0.0] * config.ARTICLE_NUM] * batch_size)
        task_3_output.extend([[0.0] * config.IMPRISONMENT_NUM] * batch_size)
    print('\ncost time: %.3fs' % (time.time() - start_time))

    # 单标签
    # task_1_result = [[np.argmax(s, axis=-1)] for s in task_1_output]
    # task_2_result = [[np.argmax(s, axis=-1)] for s in task_2_output]
    # task_3_result = np.argmax(task_3_output, axis=-1)
    #
    # result = []
    # for t1, t2, t3 in zip(task_1_result, task_2_result, task_3_result):
    #     result.append({
    #         'accusation': t1,
    #         'articles': t2,
    #         'imprisonment': util.id_2_imprisonment(t3),
    #     })
    #
    # print('write file: ', out_file + '.json')
    # with codecs.open(out_file + '.json', 'w', encoding='utf-8') as f_out:
    #     for r in result:
    #         r = util.format_result(r)
    #         print(json.dumps(r), file=f_out)

    # 多标签
    for threshold in config.TASK_THRESHOLD:
        task_1_result = [util.get_task_result(s, threshold) for s in task_1_output]
        task_2_result = [util.get_task_result(s, threshold) for s in task_2_output]
        task_3_result = np.argmax(task_3_output, axis=-1)

        result = []
        for t1, t2, t3 in zip(task_1_result, task_2_result, task_3_result):
            result.append({
                'accusation': t1,
                'articles': t2,
                'imprisonment': util.id_2_imprisonment(t3),
            })

        print('write file: ', out_file + '-' + str(threshold) + '.json')
        with codecs.open(out_file + '-' + str(threshold) + '.json', 'w', encoding='utf-8') as f_out:
            for r in result:
                r = util.format_result(r)
                print(json.dumps(r), file=f_out)


def make_batch_iter(data, batch_size, shuffle):
    data_size = len(data)

    if shuffle:
        random.shuffle(data)

    num_batches = (data_size + batch_size - 1) // batch_size
    print('total batches: ', num_batches)
    for i in range(num_batches):
        start_index = i * batch_size
        end_index = min(data_size, (i + 1) * batch_size)
        yield data[start_index: end_index]


def read_law_kb(data_dir, id_2_law, word_2_id, max_seq_len, max_doc_len):
    law_kb = []
    law_seq_len = []
    law_doc_len = []
    for i in range(len(id_2_law)):
        law_name = id_2_law[i]
        file_name = os.path.join(data_dir, str(law_name) + '.txt')
        with codecs.open(file_name, 'r', encoding='utf-8') as f_in:
            law = f_in.readline()
            law = util.refine_text(law)
            law = util.refine_doc(law, max_seq_len, max_doc_len)
            law = [util.convert_to_id_list(seq, word_2_id) for seq in law]
            law_kb.append(law)

            seq_len = [0] * max_doc_len
            for j in range(len(law)):
                seq_len[j] = len(law[j])
            law_seq_len.append(seq_len)

            law_doc_len.append(len(law))

    return pad_law_kb(law_kb), law_seq_len, law_doc_len


def read_data(data_file, word_2_id, tfidf_model_file, max_seq_len, max_doc_len):
    print('read file: ', data_file)
    with codecs.open(data_file, 'r', encoding='utf-8') as f_in:
        lines = f_in.readlines()
    print('data size: ', len(lines))

    tfidf_model = joblib.load(tfidf_model_file)

    corpus = []
    fact = []
    fact_seq_len = []
    fact_doc_len = []
    for line in lines:
        item = json.loads(line, encoding='utf-8')

        _fact = item['fact'].strip().lower()
        _fact = util.refine_text(_fact)
        corpus.append(' '.join(_fact))

        _fact = util.refine_doc(_fact, max_seq_len, max_doc_len)
        _fact = [util.convert_to_id_list(seq, word_2_id) for seq in _fact]
        fact.append(_fact)

        _fact_seq_len = [0] * max_doc_len
        for i in range(len(_fact)):
            _fact_seq_len[i] = len(_fact[i])
        fact_seq_len.append(_fact_seq_len)

        fact_doc_len.append(len(_fact))

    return fact, fact_seq_len, fact_doc_len, tfidf_model.transform(corpus).toarray()


def predict(judger, config_proto):
    assert config.CURRENT_MODEL == 'fact_law'

    word_2_id, id_2_word = util.read_dict(config.WORD_DICT)
    law_2_id, id_2_law, accu_2_id, id_2_accu = util.init_dict(config.LAW_DICT, config.ACCU_DICT)
    if os.path.exists(config.WORD2VEC_MODEL):
        embedding_matrix = util.load_embedding(config.WORD2VEC_MODEL, word_2_id.keys())
        embedding_trainable = False
    else:
        embedding_matrix = np.random.uniform(-0.5, 0.5, [config.VOCAB_SIZE, config.EMBEDDING_SIZE])
        embedding_trainable = True

    with tf.variable_scope('model', reuse=None):
        test_model = FactLaw(
            accu_num=config.ACCU_NUM, article_num=config.ARTICLE_NUM,
            top_k=config.TOP_K, tfidf_size=config.TFIDF_SIZE,
            max_seq_len=config.SEQUENCE_LEN, max_doc_len=config.DOCUMENT_LEN,
            hidden_size=config.HIDDEN_SIZE, att_size=config.ATT_SIZE, fc_size=config.FC_SIZE_S,
            embedding_matrix=embedding_matrix, embedding_trainable=embedding_trainable,
            lr=config.LR, optimizer=config.OPTIMIZER, keep_prob=config.KEEP_PROB, l2_rate=config.L2_RATE,
            is_training=False
        )

    test_data = read_data(config.TRAIN_DATA, word_2_id, config.TFIDF_MODEL, config.SEQUENCE_LEN, config.DOCUMENT_LEN)
    kb_data = read_law_kb(config.LAW_KB_DIR, id_2_law, word_2_id, config.SEQUENCE_LEN, config.DOCUMENT_LEN)

    saver = tf.train.Saver(max_to_keep=1)
    with tf.Session(config=config_proto) as sess:
        print('load model from: ' + config.MODEL_FILE)
        saver.restore(sess, config.MODEL_FILE)

        print('==========  Test  ==========')
        test_batch_iter = make_batch_iter(list(zip(*test_data)), config.BATCH_SIZE, shuffle=False)
        inference(sess, test_model, test_batch_iter, kb_data, config.TEST_RESULT, verbose=True)

        # 单标签
        # result = judger.my_test(config.TEST_DATA, config.TEST_RESULT + '.json')
        # accu_micro_f1, accu_macro_f1 = judger.calc_f1(result[0])
        # article_micro_f1, article_macro_f1 = judger.calc_f1(result[1])
        # score = judger.get_score(result)
        # print('Threshold: %.3f' % threshold)
        # print('Micro-F1 of accusation: %.3f' % accu_micro_f1)
        # print('Macro-F1 of accusation: %.3f' % accu_macro_f1)
        # print('Micro-F1 of relevant articles: %.3f' % article_micro_f1)
        # print('Macro-F1 of relevant articles: %.3f' % article_macro_f1)
        # print('Score: ', score)

        # 多标签
        for threshold in config.TASK_THRESHOLD:
            result = judger.my_test(config.TEST_DATA, config.TEST_RESULT + '-' + str(threshold) + '.json')
            accu_micro_f1, accu_macro_f1 = judger.calc_f1(result[0])
            article_micro_f1, article_macro_f1 = judger.calc_f1(result[1])
            score = judger.get_score(result)
            print('Threshold: %.3f' % threshold)
            print('Micro-F1 of accusation: %.3f' % accu_micro_f1)
            print('Macro-F1 of accusation: %.3f' % accu_macro_f1)
            print('Micro-F1 of relevant articles: %.3f' % article_micro_f1)
            print('Macro-F1 of relevant articles: %.3f' % article_macro_f1)
            print('Score: ', score)
