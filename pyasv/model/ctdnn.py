# -*- coding: utf-8 -*-


import tensorflow as tf
import sys

sys.path.append("../..")
import os
import time
import numpy as np
from pyasv.data_manage import DataManage
from pyasv.data_manage import DataManage4BigData
from tensorflow.python import debug


class CTDnn:
    def __init__(self, config, x, y=None):

        self._config = config
        self._batch_size = config.BATCH_SIZE
        self._n_gpu = config.N_GPU
        self._name = config.MODEL_NAME
        self._n_speaker = config.N_SPEAKER
        self._max_step = config.MAX_STEP
        self._is_big_dataset = config.IS_BIG_DATASET
        if self._is_big_dataset:
            self._url_of_big_dataset = config.URL_OF_BIG_DATASET
        self._lr = config.LR
        self._save_path = config.SAVE_PATH
        self._vectors = np.zeros(shape=(self._n_speaker, 400))

        if y is not None:
            self._build_train_graph(x, y)
        else:
            self._build_pred_graph(x)

    @property
    def loss(self):
        """A ``property`` member to get loss.

        Returns
        -------
        loss : ``tf.operation``
        """
        return self._loss

    @property
    def prediction(self):
        """A ``property`` member to get feature.

        Returns
        -------
        feature : ``tf.operation``
        """
        return self._prediction

    @property
    def feature(self):
        """A ``property`` member to get feature.

        Returns
        -------
        feature : ``tf.operation``
        """
        return self._feature

    def _build_pred_graph(self, x):
        _, self._feature = self._inference(x)

    def _build_train_graph(self, x, y):
        """
        Build the compute graph.
        """

        out, feature = self._inference(x)
        self._prediction = tf.nn.softmax(out)
        self._feature = feature
        self._loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(labels=y, logits=out))

    def _inference(self, frames):

        # Inference
        conv1 = self._conv2d(frames, 'conv1', [4, 8, 1, 128], [1, 1, 1, 1], 'VALID')

        pool1 = tf.nn.max_pool(conv1, ksize=[1, 2, 3, 1], strides=[1, 2, 3, 1], padding='VALID')

        conv2 = self._conv2d(pool1, 'conv2', [2, 4, 128, 256], [1, 1, 1, 1], 'VALID')

        pool2 = tf.nn.max_pool(conv2, ksize=[1, 1, 2, 1], strides=[1, 1, 2, 1], padding='VALID')

        pool2_flat = tf.reshape(pool2, [-1,
                                        pool2.get_shape().as_list()[1] *
                                        pool2.get_shape().as_list()[2] *
                                        pool2.get_shape().as_list()[3]])

        bottleneck = self._full_connect(pool2_flat, 'bottleneck', 512)

        bottleneck_t = tf.reshape(bottleneck, [-1, 512, 1])

        td1 = self._t_dnn(bottleneck_t, name='td1', shape=[5, 1, 32], strides=1)

        td1_flat = tf.reshape(td1, [-1, td1.get_shape().as_list()[1] * td1.get_shape().as_list()[2]])

        p_norm1 = self._full_connect(td1_flat, name='P_norm1', units=2000)

        p_norm1_t = tf.reshape(p_norm1, [-1, 2000, 1])

        pnorm1 = self._p_norm(p_norm1_t)

        td2 = self._t_dnn(pnorm1, name='td2', shape=[9, 1, 32], strides=1)

        td2_flat = tf.reshape(td2, [-1, td2.get_shape().as_list()[1] * td2.get_shape().as_list()[2]])

        p_norm2 = self._full_connect(td2_flat, name='P_norm2', units=2000)

        p_norm2_t = tf.reshape(p_norm2, [-1, 2000, 1])

        pnorm2 = self._p_norm(p_norm2_t)

        pnorm2_output = tf.reshape(pnorm2, [-1, 400])

        feature_layer = self._full_connect(pnorm2_output, name='feature_layer', units=400)

        output = self._full_connect(feature_layer, name='output', units=self._n_speaker)

        output += 1e-10

        return output, feature_layer,

    def _t_dnn(self, x, shape, strides, name):
        with tf.name_scope(name):
            weights = self._weights_variable(shape, name=name+'_w')
        return tf.nn.conv1d(x, weights, stride=strides, padding='SAME', name=name + "_output")

    def _conv2d(self, x, name, shape, strides, padding='SAME'):
        with tf.name_scope(name):
            weights = self._weights_variable(shape, name=name+'_w')
            biases = self._bias_variable(shape[-1], name=name+'_b')
        return tf.nn.relu(tf.nn.bias_add(tf.nn.conv2d(x, weights,
                                                      strides=strides, padding=padding), biases, name=name + "_output"))

    def _full_connect(self, x, name, units):
        with tf.name_scope(name):
            weights = self._weights_variable([x.get_shape().as_list()[-1], units], name=name+'_w')
            biases = self._bias_variable(units, name=name+'_b')
        return tf.nn.relu(tf.nn.bias_add(tf.matmul(x, weights), biases), name=name + "_output")

    @staticmethod
    def _weights_variable(shape, name='weights', stddev=0.1):
        initial = tf.truncated_normal(shape, stddev=stddev)
        return tf.get_variable(initializer=initial, name=name)

    @staticmethod
    def _bias_variable(shape, name='bias', stddev=0.1):
        initial = tf.truncated_normal([shape], stddev=stddev)
        return tf.get_variable(initializer=initial, name=name)

    def _p_norm(self, x):
        y = tf.reshape(x, [-1,400,5,1])
        squares = tf.square(y)
        sum_squares = tf.reduce_sum(squares, axis=len(y.get_shape().as_list())-2)
        root_sum_squares = tf.sqrt(sum_squares)        
        return root_sum_squares


def average_losses(loss):
    tf.add_to_collection('losses', loss)

    # Assemble all of the losses for the current tower only.
    losses = tf.get_collection('losses')

    # Calculate the total loss for the current tower.
    regularization_losses = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)
    total_loss = tf.add_n(losses + regularization_losses, name='total_loss')

    # Compute the moving average of all individual losses and the total loss.
    loss_averages = tf.train.ExponentialMovingAverage(0.9, name='avg')
    loss_averages_op = loss_averages.apply(losses + [total_loss])

    with tf.control_dependencies([loss_averages_op]):
        total_loss = tf.identity(total_loss)
    return total_loss


def average_gradients(tower_grads):
    average_grads = []
    for grad_and_vars in zip(*tower_grads):
        # Note that each grad_and_vars looks like the following:
        #   ((grad0_gpu0, var0_gpu0), ... , (grad0_gpuN, var0_gpuN))
        grads = [g for g, _ in grad_and_vars]
        # Average over the 'tower' dimension.
        grad = tf.stack(grads, 0)
        grad = tf.reduce_mean(grad, 0)

        # Keep in mind that the Variables are redundant because they are shared
        # across towers. So .. we will just return the first tower's pointer to
        # the Variable.
        v = grad_and_vars[0][1]
        grad_and_var = (grad, v)
        average_grads.append(grad_and_var)
    return average_grads


def feed_all_gpu(inp_dict, models, payload_per_gpu, batch_x, batch_y):
    for i in range(len(models)):
        x, y, _, _, _, _ = models[i]
        start_pos = i * payload_per_gpu
        stop_pos = (i + 1) * payload_per_gpu
        inp_dict[x] = batch_x[start_pos:stop_pos]
        inp_dict[y] = batch_y[start_pos:stop_pos]
    return inp_dict


def _no_gpu(config, train, validation):
    tf.reset_default_graph()
    with tf.Session() as sess:
        learning_rate = config.LR
        print('build model...')
        opt = tf.train.AdamOptimizer(learning_rate=learning_rate)
        x = tf.placeholder(tf.float32, [None, 9, 40, 1])
        y = tf.placeholder(tf.float32, [None, config.N_SPEAKER])
        model = CTDnn(config, x, y)
        pred = model.prediction
        loss = model.loss
        feature = model.feature
        train_op = opt.minimize(loss)
        vectors = dict()
        print("done...")
        print('run train op...')
        sess.run(tf.global_variables_initializer())
        saver = tf.train.Saver()
        for epoch in range(config.MAX_STEP):
            start_time = time.time()
            avg_loss = 0.0
            total_batch = int(train.num_examples / config.BATCH_SIZE) - 1
            print('\n---------------------')
            print('Epoch:%d, lr:%.4f, total_batch=%d' % (epoch, config.LR, total_batch))
            feature_ = None
            ys = None
            for batch_id in range(total_batch):
                batch_x, batch_y = train.next_batch
                batch_x = batch_x.reshape(-1, 9, 40, 1)
                _, _loss, batch_feature = sess.run([train_op, loss, feature],
                                                   feed_dict={x: batch_x, y: batch_y})

                avg_loss += _loss
                if feature_ is None:
                    feature_ = batch_feature
                else:
                    feature_ = np.concatenate((feature_, batch_feature), 0)
                if ys is None:
                    ys = batch_y
                else:
                    ys = np.concatenate((ys, batch_y), 0)
                print("batch_%d  batch_loss=%.4f"%(batch_id, _loss), end='\r')
            print('\n')
            train.reset_batch_counter()
            for spkr in range(config.N_SPEAKER):
                if len(feature_[np.argmax(ys, 1) == spkr]):
                    vector = np.mean(feature_[np.argmax(ys, 1) == spkr], axis=0)
                    if spkr in vectors.keys():
                        vector = (vectors[spkr] + vector) / 2
                    else:
                        vector = vector
                    vectors[spkr] = vector
                else:
                    if spkr not in vectors.keys():
                        vectors[spkr] = np.zeros(400, dtype=np.float32)
            avg_loss /= total_batch
            print('Train loss:%.4f' % (avg_loss))
            total_batch = int(validation.num_examples / config.BATCH_SIZE) - 1
            preds = None
            feature_ = None
            ys = None
            for batch_idx in range(total_batch):
                print("validation in batch_%d..."%batch_idx, end='\r')
                batch_x, batch_y = validation.next_batch
                batch_y, batch_pred, batch_feature = sess.run([y, pred, feature],
                                                              feed_dict={x:batch_x, y:batch_y})
                if preds is None:
                    preds = batch_pred
                else:
                    preds = np.concatenate((preds, batch_pred), 0)
                if feature_ is None:
                    feature_ = batch_feature
                else:
                    feature_ = np.concatenate((feature_, batch_feature), 0)
                if ys is None:
                    ys = batch_y
                else:
                    ys = np.concatenate((ys, batch_y), 0)
            validation.reset_batch_counter()
            vec_preds = []
            for sample in range(feature_.shape[0]):
                score = -100
                pred = -1
                for spkr in vectors.keys():
                    if cosine(vectors[spkr], feature_[sample]) > score:
                        score = cosine(vectors[spkr], feature_[sample])
                        pred = int(spkr)
                vec_preds.append(pred)
            correct_pred = np.equal(np.argmax(ys, 1), vec_preds)
            val_accuracy = np.mean(np.array(correct_pred, dtype='float'))
            print('Val Accuracy: %0.4f%%' % (100.0 * val_accuracy))
            stop_time = time.time()
            elapsed_time = stop_time-start_time
            saver.save(sess=sess, save_path=os.path.join(model._save_path, model._name + ".ckpt"))
            print('Cost time: ' + str(elapsed_time) + ' sec.')
        print('training done.')


def _multi_gpu(config, train, validation, debug_mode=False):
    tf.reset_default_graph()
    with tf.Session() as sess:
        with tf.device('/cpu:0'):
            learning_rate = config.LR
            # opt = tf.train.GradientDescentOptimizer(learning_rate=learning_rate)
            opt = tf.train.AdamOptimizer(learning_rate=learning_rate)
            print('build model...')
            print('build model on gpu tower...')
            models = []
            for gpu_id in range(config.N_GPU):
                with tf.device('/gpu:%d' % gpu_id):
                    print('tower:%d...' % gpu_id)
                    with tf.name_scope('tower_%d' % gpu_id):
                        with tf.variable_scope('cpu_variables', reuse=tf.AUTO_REUSE):
                            x = tf.placeholder(tf.float32, [None, 9, 40, 1])
                            y = tf.placeholder(tf.float32, [None, train.spkr_num])
                            model = CTDnn(config, x, y)
                            pred = model.prediction
                            feature = model.feature
                            loss = model.loss
                            grads = opt.compute_gradients(loss)
                            models.append((x, y, pred, loss, grads, feature))
            print('build model on gpu tower done.')

            print('reduce model on cpu...')
            tower_x, tower_y, tower_preds, tower_losses, tower_grads, tower_feature = zip(*models)
            aver_loss_op = tf.reduce_mean(tower_losses)
            apply_gradient_op = opt.apply_gradients(average_gradients(tower_grads))
            get_feature = tf.reshape(tf.stack(tower_feature, 0), [-1, 400])

            all_y = tf.reshape(tf.stack(tower_y, 0), [-1, config.N_SPEAKER])

            all_pred = tf.reshape(tf.stack(tower_preds, 0), [-1, config.N_SPEAKER])

            vectors = dict()

            print('reduce model on cpu done.')

            print('run train op...')
            sess.run(tf.global_variables_initializer())
            if debug_mode:
                sess = debug.LocalCLIDebugWrapperSession(sess=sess)
            saver = tf.train.Saver()

            for epoch in range(config.MAX_STEP):
                start_time = time.time()
                payload_per_gpu = int(config.BATCH_SIZE//config.N_GPU)
                if config.BATCH_SIZE % config.N_GPU:
                    print("Warning: Batch size can't to be divisible of N_GPU")
                total_batch = int(train.num_examples / config.BATCH_SIZE) - 1
                avg_loss = 0.0
                print('\n---------------------')
                print('Epoch:%d, lr:%.4f, total_batch:%d' % (epoch, config.LR, total_batch))
                feature_ = None
                ys = None

                # temp log
                for batch_idx in range(total_batch):
                    batch_x, batch_y = train.next_batch
                    batch_x = batch_x.reshape(-1, 9, 40, 1)
                    # Below line is required for big data set
                    # batch_y = np.array((np.eye(config.N_SPEAKER)[np.array(batch_y).reshape(-1)]), dtype=np.float32)
                    inp_dict = dict()
                    # print("data part done...")
                    inp_dict = feed_all_gpu(inp_dict, models, payload_per_gpu, batch_x, batch_y)
                    _, _loss, batch_feature = sess.run([apply_gradient_op, aver_loss_op, get_feature], inp_dict)
                    # print("train part done...")
                    avg_loss += _loss
                    if ys is None:
                        ys = batch_y
                    else:
                        ys = np.concatenate((ys, batch_y), 0)
                    if feature_ is None:
                        feature_ = batch_feature
                    else:
                        feature_ = np.concatenate((feature_, batch_feature), 0)
                    print("batch_%d, batch_loss=%.4f, payload_per_gpu=%d"%(batch_idx, _loss, payload_per_gpu), end='\r')
                print("\n")
                train.reset_batch_counter()
                for spkr in range(config.N_SPEAKER):
                    if len(feature_[np.argmax(ys, 1) == spkr]):
                        vector = np.mean(feature_[np.argmax(ys, 1) == spkr], axis=0)
                        if spkr in vectors.keys():
                            vector = (vectors[spkr] + vector) / 2
                        else:
                            vector = vector
                        vectors[spkr] = vector
                    else:
                        if spkr not in vectors.keys():
                            vectors[spkr] = np.zeros(400, dtype=np.float32)
                # print("vector part done....")
                avg_loss /= total_batch
                print('Train loss:%.4f' % (avg_loss))

                val_payload_per_gpu = int(config.BATCH_SIZE//config.N_GPU)
                if config.BATCH_SIZE % config.N_GPU:
                    print("Warning: Batch size can't to be divisible of N_GPU")

                total_batch = int(validation.num_examples / config.BATCH_SIZE) - 1
                preds = None
                ys = None
                feature_ = None
                for batch_idx in range(total_batch):
                    batch_x, batch_y = validation.next_batch
                    batch_x = batch_x.reshape(-1, 9, 40, 1)
                    # Below line is required for big data set
                    # batch_y = np.array((np.eye(config.N_SPEAKER)[np.array(batch_y).reshape(-1)]), dtype=np.float32)
                    inp_dict = feed_all_gpu({}, models, val_payload_per_gpu, batch_x, batch_y)

                    batch_pred, batch_y_, batch_feature = sess.run([all_pred, all_y, get_feature], inp_dict)
                    if preds is None:
                        preds = batch_pred
                    else:
                        preds = np.concatenate((preds, batch_pred), 0)
                    if feature_ is None:
                        feature_ = batch_feature
                    else:
                        feature_ = np.concatenate((feature_, batch_feature), 0)
                    if ys is None:
                        ys = batch_y_
                    else:
                        ys = np.concatenate((ys, batch_y_), 0)
                    
                validation.reset_batch_counter()
                vec_preds = []
                for sample in range(feature_.shape[0]):
                    score = -100
                    pred = -1
                    for spkr in vectors.keys():
                        if cosine(vectors[spkr], feature_[sample]) > score:
                            score = cosine(vectors[spkr], feature_[sample])
                            pred = int(spkr)
                    vec_preds.append(pred)
                correct_pred = np.equal(np.argmax(ys, 1), vec_preds)
                val_accuracy = np.mean(np.array(correct_pred, dtype='float'))
                print('Val Accuracy: %0.4f%%' % (100.0 * val_accuracy))
                saver.save(sess=sess, save_path=os.path.join(model._save_path, model._name + ".ckpt"))
                stop_time = time.time()
                elapsed_time = stop_time-start_time
                print('Cost time: ' + str(elapsed_time) + ' sec.')
            print('training done.')


def cosine(vector1, vector2):
    return np.dot(vector1, vector2) / (np.linalg.norm(vector1) * (np.linalg.norm(vector2)))


def run(config, train, validation, debug_mode=False):
    """Train CTDNN model.

    Parameters
    ----------
    config : ``config``
        the config of model.
    train : ``DataManage``
        train dataset.
    validation
        validation dataset.
    """
    if config.N_GPU == 0:
        _no_gpu(config, train, validation)
    else:
        if os.path.exists('./tmp'):
            os.rename('./tmp', './tmp-backup')
        os.system('nvidia-smi -q -d Memory |grep -A4 GPU|grep Free > ./tmp')
        memory_gpu=[int(x.split()[2]) for x in open('tmp','r').readlines()]
        gpu_list = []
        for gpu in range(config.N_GPU):
            gpu_list.append(str(np.argmax(memory_gpu)))
            memory_gpu[np.argmax(memory_gpu)] = -10000
        s = ""
        for i in range(config.N_GPU):
            if i != 0:
                s += ','
            s += str(gpu_list[i])
        os.environ['CUDA_VISIBLE_DEVICES'] = s
        os.remove('./tmp')
        _multi_gpu(config, train, validation, debug_mode)


def restore(config, enroll, test):
    with tf.Graph().as_default() as g:
        assert type(enroll) == (DataManage or DataManage4BigData)
        assert type(enroll) == (DataManage or DataManage4BigData)
        with tf.Session() as sess:
            x = tf.placeholder(tf.float32, [None, 9, 40, 1])
            if config.N_GPU == 0:
                model = CTDnn(config, x)
            else:
                with tf.variable_scope('cpu_variables', reuse=tf.AUTO_REUSE):
                    model = CTDnn(config, x)
            get_feature = model.feature
            saver = tf.train.Saver()
            saver.restore(sess, os.path.join(config.SAVE_PATH, config.MODEL_NAME + ".ckpt"))
            print("restore model succeed.")
            total_batch = int(enroll.num_examples / config.BATCH_SIZE)
            ys = None
            feature_ = None
            print("enrolling...")
            for batch in range(total_batch):
                batch_x, batch_y = enroll.next_batch

                if batch_x.shape[0] != enroll.batch_size:
                    print("Abandon the last batch because it is not enough.")
                    break

                batch_feature = sess.run(get_feature, feed_dict={x: batch_x})
                if feature_ is None:
                    feature_ = batch_feature
                else:
                    feature_ = np.concatenate((feature_, batch_feature), 0)
                if ys is None:
                    ys = batch_y
                else:
                    ys = np.concatenate((ys, batch_y), 0)
            enrolled_vector = {}
            for i in range(enroll.spkr_num):
                enrolled_vector[i] = np.mean(feature_[np.argmax(ys, axis=1) == i], 0)

            print("testing...")
            total_batch = int(test.num_examples / config.BATCH_SIZE)
            for batch in range(total_batch):
                batch_x, batch_y = test.next_batch

                if batch_x.shape[0] != test.batch_size:
                    print("Abandon the last batch because it is not enough.")
                    break

                batch_feature = sess.run(get_feature, feed_dict={x: batch_x})
                if feature_ is None:
                    feature_ = batch_feature
                else:
                    feature_ = np.concatenate((feature_, batch_feature), 0)
                if ys is None:
                    ys = batch_y
                else:
                    ys = np.concatenate((ys, batch_y), 0)
            support = 0
            all_ = 0
            print("writing the result in %s"%config.SAVE_PATH + "/result.txt")
            result = []
            with open(os.path.join(config.SAVE_PATH, 'result.txt'), 'w') as f:
                vec_id = 0
                for vec in feature_:
                    score = -1
                    pred = None
                    scores = []
                    for key in enrolled_vector.keys():
                        tmp_score = cosine(vec, enrolled_vector[key])
                        scores.append(tmp_score)
                        if tmp_score > score:
                            score = tmp_score
                            pred = key
                            if pred == np.argmax(ys, axis=1)[vec_id]:
                                support += 1
                            all_ += 1
                    string = "No.%d vector, pred:" % vec_id + str(pred) + " "
                    string += str(pred==np.argmax(ys, axis=1)[vec_id])+ " Score list:" + str(scores) + '\n'
                    result.append(string)
                    vec_id += 1
                f.writelines("Acc:%.4f  Num_of_true:%d\n"%(support/all_, support))
                for line in result:
                    f.writelines(line)
            print("done.")


def _main():
    """
    Test model.
    """
    from pyasv.data_manage import DataManage
    from pyasv import Config
    sys.path.append("../..")

    con = Config(name='ctdnn', n_speaker=100, batch_size=64*2, n_gpu=2, max_step=5, is_big_dataset=False,
                 learning_rate=0.001, save_path='./save')
    #con.save('ctdnn')
    x = np.random.random([6500, 9, 40, 1])
    y = np.random.randint(0, 99, [6500, 1])
    enroll = DataManage(x, y, con)
    train = enroll

    x = np.random.random([1500, 9, 40, 1])
    y = np.random.randint(0, 99, [1500, 1])
    test = DataManage(x, y, con)
    validation = test

    # run(con, train, validation, False)
    restore(con, enroll, test)


if __name__ == '__main__':
    _main()