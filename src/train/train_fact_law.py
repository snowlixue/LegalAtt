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
        tmp = [[config.PAD_ID] * config.SEQUENCE_LEN] * config.DOCUMENT_LEN
        for i in range(len(fact)):
            tmp[i][:len(fact[i])] = fact[i]
        new_batch.append(tmp)
    return new_batch


def pad_law_kb(law_kb):
    new_law_kb = []
    for art in law_kb:
        tmp = [[config.PAD_ID] * config.SEQUENCE_LEN] * config.DOCUMENT_LEN
        for i in range(len(art)):
            tmp[i][:len(art[i])] = art[i]
        new_law_kb.append(tmp)
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

        fact, fact_seq_len, fact_doc_len, tfidf, _, _, _ = list(zip(*batch))

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

        _top_k_indices, _art_att, _task_2_output, _task_3_output = sess.run(
            [model.top_k_indices, model.art_att, model.task_2_output, model.task_3_output],
            feed_dict=feed_dict
        )
        _task_1_output = [0.0] * config.ARTICLE_NUM
        for j, k in enumerate(_top_k_indices):
            _task_1_output[k] = _art_att[j]
        task_1_output.extend(_task_1_output)
        task_2_output.extend(_task_2_output)
        task_3_output.extend(_task_3_output)
    print('\ncost time: %.3fs' % (time.time() - start_time))

    # 单标签
    # task_1_result = [[np.argmax(s, axis=-1)] for s in task_1_output]
    # task_2_result = np.argmax(task_2_output, axis=-1)
    # task_3_result = [[np.argmax(s, axis=-1)] for s in task_3_output]
    #
    # result = []
    # for t1, t2, t3 in zip(task_1_result, task_2_result, task_3_result):
    #     result.append({
    #         'articles': t1,
    #         'imprisonment': util.id_2_imprisonment(t2),
    #         'accusation': t3
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
        task_2_result = np.argmax(task_2_output, axis=-1)
        task_3_result = [util.get_task_result(s, threshold) for s in task_3_output]

        result = []
        for t1, t2, t3 in zip(task_1_result, task_2_result, task_3_result):
            result.append({
                'articles': t1,
                'imprisonment': util.id_2_imprisonment(t2),
                'accusation': t3
            })

        print('write file: ', out_file + '-' + str(threshold) + '.json')
        with codecs.open(out_file + '-' + str(threshold) + '.json', 'w', encoding='utf-8') as f_out:
            for r in result:
                r = util.format_result(r)
                print(json.dumps(r), file=f_out)


def run_epoch(sess, model, batch_iter, kb_data, verbose=True):
    law_kb, law_seq_len, law_doc_len = kb_data

    steps = 0
    total_loss = 0.0
    _global_step = 0
    start_time = time.time()
    for batch in batch_iter:
        fact, fact_seq_len, fact_doc_len, tfidf, accu, article, imprisonment = list(zip(*batch))

        batch_size = len(fact)
        fact = pad_fact_batch(fact)

        feed_dict = {
            model.fact: fact,
            model.fact_seq_len: fact_seq_len,
            model.fact_doc_len: fact_doc_len,
            model.tfidf: tfidf,
            model.law_kb: [law_kb] * batch_size,
            model.law_seq_len: [law_seq_len] * batch_size,
            model.law_doc_len: [law_doc_len] * batch_size,
            model.accu: accu,
            model.article: article,
            model.imprisonment: imprisonment
        }

        _, _loss, _global_step = sess.run(
            [model.train_op, model.loss, model.global_step],
            feed_dict=feed_dict
        )

        steps += 1
        total_loss += _loss
        if verbose and steps % 1000 == 1:
            current_time = time.time()
            print('After %5d batch(es), global step is %5d, loss is %.3f, cost time %.3fs'
                  % (steps, _global_step, _loss, current_time - start_time))
            start_time = current_time

    return total_loss / steps, _global_step


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
            law = law[:max_doc_len]
            law_kb.append(law)

            seq_len = [0] * max_doc_len
            for j, seq in enumerate(law):
                seq_len[j] = len(seq)
            law_seq_len.append(seq_len)

            law_doc_len.append(len(law))

    return pad_law_kb(law_kb), law_seq_len, law_doc_len


def read_data(data_file, word_2_id, law_2_id, accu_2_id, tfidf_model_file, max_seq_len, max_doc_len):
    print('read file: ', data_file)
    with codecs.open(data_file, 'r', encoding='utf-8') as f_in:
        lines = f_in.readlines()
    print('data size: ', len(lines))

    tfidf_model = joblib.load(tfidf_model_file)

    corpus = []
    fact = []
    fact_seq_len = []
    fact_doc_len = []
    accu = []
    article = []
    imprisonment = []
    for line in lines:
        item = json.loads(line, encoding='utf-8')

        _fact = item['fact'].strip().lower()
        _fact = util.refine_text(_fact)
        corpus.append(' '.join(_fact))

        _fact = util.refine_doc(_fact, max_seq_len, max_doc_len)
        _fact = [util.convert_to_id_list(seq, word_2_id) for seq in _fact]
        _fact = _fact[:max_doc_len]
        fact.append(_fact)

        _fact_seq_len = [0] * max_doc_len
        for i, seq in enumerate(_fact):
            _fact_seq_len[i] = len(seq)
        fact_seq_len.append(_fact_seq_len)

        fact_doc_len.append(len(_fact))

        tmp = item['meta']['accusation']
        for i in range(len(tmp)):
            tmp[i] = tmp[i].replace('[', '').replace(']', '')
        tmp = util.convert_to_id_list(tmp, accu_2_id)
        _accu = [0.0] * config.ACCU_NUM
        for i in tmp:
            _accu[i] += 1.0 / len(tmp)
        accu.append(_accu)

        tmp = [str(t) for t in item['meta']['relevant_articles']]
        tmp = util.convert_to_id_list(tmp, law_2_id)
        _article = [0] * config.ARTICLE_NUM
        for i in tmp:
            _article[i] = 1
        article.append(_article)

        tmp = item['meta']['term_of_imprisonment']
        tmp = util.imprisonment_2_id(tmp)
        _imprisonment = [0] * config.IMPRISONMENT_NUM
        _imprisonment[tmp] = 1
        imprisonment.append(_imprisonment)

    return fact, fact_seq_len, fact_doc_len, tfidf_model.transform(corpus).toarray(), accu, article, imprisonment


def train(judger, config_proto):
    assert config.CURRENT_MODEL == 'fact_law'

    if not os.path.exists(config.MODEL_DIR):
        os.makedirs(config.MODEL_DIR)
    if not os.path.exists(config.RESULT_DIR):
        os.makedirs(config.RESULT_DIR)

    word_2_id, id_2_word = util.read_dict(config.WORD_DICT)
    law_2_id, id_2_law, accu_2_id, id_2_accu = util.init_dict(config.LAW_DICT, config.ACCU_DICT)
    if os.path.exists(config.WORD2VEC_MODEL):
        embedding_matrix = util.load_embedding(config.WORD2VEC_MODEL, word_2_id.keys())
        embedding_trainable = False
    else:
        embedding_matrix = np.random.uniform(-0.5, 0.5, [config.VOCAB_SIZE, config.EMBEDDING_SIZE])
        embedding_trainable = True

    with tf.variable_scope('model', reuse=None):
        train_model = FactLaw(
            accu_num=config.ACCU_NUM, article_num=config.ARTICLE_NUM, imprisonment_num=config.IMPRISONMENT_NUM,
            top_k=config.TOP_K, tfidf_size=config.TFIDF_SIZE,
            max_seq_len=config.SEQUENCE_LEN, max_doc_len=config.DOCUMENT_LEN,
            hidden_size=config.HIDDEN_SIZE, att_size=config.ATT_SIZE,
            fc_size_1=config.FC_SIZE_M, fc_size_2=config.FC_SIZE_S,
            embedding_matrix=embedding_matrix, embedding_trainable=embedding_trainable,
            lr=config.LR, optimizer=config.OPTIMIZER, keep_prob=config.KEEP_PROB, l2_rate=config.L2_RATE,
            is_training=True
        )
    with tf.variable_scope('model', reuse=True):
        valid_model = FactLaw(
            accu_num=config.ACCU_NUM, article_num=config.ARTICLE_NUM, imprisonment_num=config.IMPRISONMENT_NUM,
            top_k=config.TOP_K, tfidf_size=config.TFIDF_SIZE,
            max_seq_len=config.SEQUENCE_LEN, max_doc_len=config.DOCUMENT_LEN,
            hidden_size=config.HIDDEN_SIZE, att_size=config.ATT_SIZE,
            fc_size_1=config.FC_SIZE_M, fc_size_2=config.FC_SIZE_S,
            embedding_matrix=embedding_matrix, embedding_trainable=embedding_trainable,
            lr=config.LR, optimizer=config.OPTIMIZER, keep_prob=config.KEEP_PROB, l2_rate=config.L2_RATE,
            is_training=False
        )

    train_data = read_data(config.TRAIN_DATA, word_2_id, law_2_id, accu_2_id, config.TFIDF_MODEL,
                           config.SEQUENCE_LEN, config.DOCUMENT_LEN)
    valid_data = read_data(config.VALID_DATA, word_2_id, law_2_id, accu_2_id, config.TFIDF_MODEL,
                           config.SEQUENCE_LEN, config.DOCUMENT_LEN)
    kb_data = read_law_kb(config.LAW_KB_DIR, id_2_law, word_2_id, config.SEQUENCE_LEN, config.DOCUMENT_LEN)

    best_accu_micro_f1 = 0.0
    best_accu_macro_f1 = 0.0
    best_article_micro_f1 = 0.0
    best_article_macro_f1 = 0.0
    best_score = [0.0, 0.0, 0.0]
    saver = tf.train.Saver(max_to_keep=1)
    with tf.Session(config=config_proto) as sess:
        tf.global_variables_initializer().run()
        saver.save(sess, config.MODEL_FILE)

        for i in range(config.NUM_EPOCH):
            print('==========  Epoch %2d Train  ==========' % (i + 1))
            train_batch_iter = make_batch_iter(list(zip(*train_data)), config.BATCH_SIZE, shuffle=True)
            train_loss, global_step = run_epoch(sess, train_model, train_batch_iter, kb_data, verbose=True)
            print('The average train loss of epoch %2d is %.3f' % ((i + 1), train_loss))

            print('==========  Epoch %2d Valid  ==========' % (i + 1))
            valid_batch_iter = make_batch_iter(list(zip(*valid_data)), config.BATCH_SIZE, shuffle=False)
            inference(sess, valid_model, valid_batch_iter, kb_data, config.VALID_RESULT, verbose=True)

            # 单标签
            # result = judger.my_test(config.VALID_DATA, config.VALID_RESULT + '.json')
            # accu_micro_f1, accu_macro_f1 = judger.calc_f1(result[0])
            # article_micro_f1, article_macro_f1 = judger.calc_f1(result[1])
            # score = judger.get_score(result)
            # print('Threshold: %.3f' % threshold)
            # print('Micro-F1 of accusation: %.3f' % accu_micro_f1)
            # print('Macro-F1 of accusation: %.3f' % accu_macro_f1)
            # print('Micro-F1 of relevant articles: %.3f' % article_micro_f1)
            # print('Macro-F1 of relevant articles: %.3f' % article_macro_f1)
            # print('Score: ', score)
            #
            # if best_score[0] < score[0]:
            #     best_accu_micro_f1 = accu_micro_f1
            #     best_accu_macro_f1 = accu_macro_f1
            #     best_article_micro_f1 = article_micro_f1
            #     best_article_macro_f1 = article_macro_f1
            #     best_score = score
            #     print('Saving model ...')
            #     saver.save(sess, config.MODEL_FILE)

            # 多标签
            for threshold in config.TASK_THRESHOLD:
                result = judger.my_test(config.VALID_DATA, config.VALID_RESULT + '-' + str(threshold) + '.json')
                accu_micro_f1, accu_macro_f1 = judger.calc_f1(result[0])
                article_micro_f1, article_macro_f1 = judger.calc_f1(result[1])
                score = judger.get_score(result)
                print('Threshold: %.3f' % threshold)
                print('Micro-F1 of accusation: %.3f' % accu_micro_f1)
                print('Macro-F1 of accusation: %.3f' % accu_macro_f1)
                print('Micro-F1 of relevant articles: %.3f' % article_micro_f1)
                print('Macro-F1 of relevant articles: %.3f' % article_macro_f1)
                print('Score: ', score)

                if best_score[0] < score[0]:
                    best_accu_micro_f1 = accu_micro_f1
                    best_accu_macro_f1 = accu_macro_f1
                    best_article_micro_f1 = article_micro_f1
                    best_article_macro_f1 = article_macro_f1
                    best_score = score
                    print('Saving model ...')
                    saver.save(sess, config.MODEL_FILE)

    print('Best micro-F1 of accusation is: %.3f' % best_accu_micro_f1)
    print('Best macro-F1 of accusation is: %.3f' % best_accu_macro_f1)
    print('Best micro-F1 of relevant articles: %.3f' % best_article_micro_f1)
    print('Best macro-F1 of relevant articles: %.3f' % best_article_macro_f1)
    print('Best score is: ', best_score)