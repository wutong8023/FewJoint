#!/usr/bin/env python
from typing import List, Tuple, Dict
import argparse, copy
import logging
import sys
import torch
import random
import os
import json
import pickle
# my staff
from utils.data_loader import FewShotRawDataLoader
from utils.preprocessor import FeatureConstructor, BertInputBuilder, FewShotOutputBuilder, make_dict, \
    save_feature, load_feature, make_preprocessor, make_label_mask, make_word_dict, FewShotSupportFeature
from utils.opt import define_args, basic_args, train_args, test_args, preprocess_args, model_args, option_check
from utils.device_helper import prepare_model, set_device_environment
from utils.trainer import FewShotTrainer, SchemaFewShotTrainer, FineTuneTrainer, prepare_optimizer
from utils.tester import FewShotTester, SchemaFewShotTester, FineTuneTester, eval_check_points
from utils.model_helper import make_model, load_model, make_finetune_model

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S',
                    level=logging.INFO,
                    stream=sys.stdout)
logger = logging.getLogger(__name__)


def get_training_data_and_feature(opt, data_loader, preprocessor):
    """ prepare feature and data """
    if opt.load_feature:
        try:
            train_features, (train_slot_label2id, train_slot_id2label), \
                (train_intent_label2id, train_intent_id2label) = \
                load_feature(opt.train_path.replace('.json', '.saved.pk'))
            dev_features, (dev_slot_label2id, dev_slot_id2label), \
                (dev_intent_label2id, dev_intent_id2label) = load_feature(opt.dev_path.replace('.json', '.saved.pk'))
        except FileNotFoundError:
            opt.load_feature, opt.save_feature = False, True  # Not a saved feature file yet, make it
            train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label),\
                dev_features, (dev_slot_label2id, dev_slot_id2label), (dev_intent_label2id, dev_intent_id2label) = \
                get_training_data_and_feature(opt, data_loader, preprocessor)
            opt.load_feature, opt.save_feature = True, False  # restore option
    else:
        train_examples, _, train_max_support_size = data_loader.load_data(path=opt.train_path)
        dev_examples, _, dev_max_support_size = data_loader.load_data(path=opt.dev_path)
        (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label) = \
            make_dict(opt, train_examples)
        (dev_slot_label2id, dev_slot_id2label), (dev_intent_label2id, dev_intent_id2label) = \
            make_dict(opt, dev_examples)
        logger.info(' Finish train dev prepare dict ')
        train_features = preprocessor.construct_feature(train_examples, train_max_support_size,
                                                        train_slot_label2id, train_slot_id2label,
                                                        train_intent_label2id, train_intent_id2label)
        dev_features = preprocessor.construct_feature(dev_examples, dev_max_support_size,
                                                      dev_slot_label2id, dev_slot_id2label,
                                                      dev_intent_label2id, dev_intent_id2label)
        logger.info(' Finish prepare train dev features ')
        if opt.do_debug:
            print('train_slot_label2id: {}'.format(train_slot_label2id))
            print('train_intent_label2id: {}'.format(train_intent_label2id))
            print('dev_slot_label2id: {}'.format(dev_slot_label2id))
            print('dev_intent_label2id: {}'.format(dev_intent_label2id))
            print('train_examples: {}'.format(len(train_examples), train_examples))
            print('train_features: {}'.format(len(train_features), train_features))
        if opt.save_feature:
            save_feature(opt.train_path.replace('.json', '.saved.pk'),
                         train_features, train_slot_label2id, train_slot_id2label,
                         train_intent_label2id, train_intent_id2label)
            save_feature(opt.dev_path.replace('.json', '.saved.pk'),
                         dev_features, dev_slot_label2id, dev_slot_id2label, dev_intent_label2id, dev_intent_id2label)
    return train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label), \
        dev_features, (dev_slot_label2id, dev_slot_id2label), (dev_intent_label2id, dev_intent_id2label)


def get_training_data_feature(opt, data_loader, preprocessor):
    """ prepare feature and data """
    if opt.load_feature:
        try:
            train_features, (train_slot_label2id, train_slot_id2label), \
                (train_intent_label2id, train_intent_id2label) = \
                load_feature('ft_' + opt.train_path.replace('.json', '.saved.pk'))
        except FileNotFoundError:
            opt.load_feature, opt.save_feature = False, True  # Not a saved feature file yet, make it
            train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label) \
                = get_training_data_feature(opt, data_loader, preprocessor)
            opt.load_feature, opt.save_feature = True, False  # restore option
    else:
        train_examples, _, train_max_support_size = data_loader.load_data(path=opt.train_path)
        dev_examples, _, dev_max_support_size = data_loader.load_data(path=opt.dev_path)

        train_examples.extend(dev_examples)

        (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label) = \
            make_dict(opt, train_examples)
        logger.info(' fine-tune :: Finish train dev prepare dict ')
        train_features = preprocessor.construct_feature(train_examples, train_max_support_size,
                                                        train_slot_label2id, train_slot_id2label,
                                                        train_intent_label2id, train_intent_id2label)
        logger.info(' fine-tune :: Finish prepare train dev features ')
        if opt.do_debug:
            print('fine-tune :: train_slot_label2id: {}'.format(train_slot_label2id))
            print('fine-tune :: train_intent_label2id: {}'.format(train_intent_label2id))
            print('fine-tune :: train_examples: {} - {}'.format(len(train_examples), train_examples))
            print('fine-tune :: train_features: {} - {}'.format(len(train_features), train_features))
        if opt.save_feature:
            save_feature('ft_' + opt.train_path.replace('.json', '.saved.pk'),
                         train_features, train_slot_label2id, train_slot_id2label,
                         train_intent_label2id, train_intent_id2label)
    return train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label)


def get_testing_data_feature(opt, data_loader, preprocessor):
    """ prepare feature and data """
    if opt.load_feature:
        try:
            test_features, (test_slot_label2id, test_slot_id2label), (test_intent_label2id, test_intent_id2label) = \
                load_feature(opt.test_path.replace('.json', '.saved.pk'))
        except FileNotFoundError:
            opt.load_feature, opt.save_feature = False, True  # Not a saved feature file yet, make it
            test_features, (test_slot_label2id, test_slot_id2label), (test_intent_label2id, test_intent_id2label) = \
                get_testing_data_feature(opt, data_loader, preprocessor)
            opt.load_feature, opt.save_feature = True, False  # restore option
    else:
        test_examples, test_max_len, test_max_support_size = data_loader.load_data(path=opt.test_path)
        (test_slot_label2id, test_slot_id2label), (test_intent_label2id, test_intent_id2label) = \
            make_dict(opt, test_examples)
        logger.info(' Finish prepare test dict')
        test_features = preprocessor.construct_feature(
            test_examples, test_max_support_size, test_slot_label2id, test_slot_id2label,
            test_intent_label2id, test_intent_id2label)
        logger.info(' Finish prepare test feature')
        if opt.do_debug:
            print('test_slot_label2id: {}'.format(test_slot_label2id))
            print('test_slot_id2label: {}'.format(test_slot_id2label))
        if opt.save_feature:
            save_feature(opt.test_path.replace('.json', '.saved.pk'),
                         test_features, test_slot_label2id, test_slot_id2label,
                         test_intent_label2id, test_intent_id2label)
    return test_features, (test_slot_label2id, test_slot_id2label), (test_intent_label2id, test_intent_id2label)


def get_support_data_feature(opt, data_loader, preprocessor):
    """ prepare feature and data """
    if opt.load_feature:
        try:
            train_features, (train_slot_label2id, train_slot_id2label), \
                (train_intent_label2id, train_intent_id2label) = \
                load_feature('ft_' + opt.train_path.replace('.json', '.saved.pk'))
        except FileNotFoundError:
            opt.load_feature, opt.save_feature = False, True  # Not a saved feature file yet, make it
            train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label) \
                = get_training_data_feature(opt, data_loader, preprocessor)
            opt.load_feature, opt.save_feature = True, False  # restore option
    else:
        train_examples, _, train_max_support_size = data_loader.load_data(path=opt.train_path)
        dev_examples, _, dev_max_support_size = data_loader.load_data(path=opt.dev_path)
        test_examples, _, test_max_support_size = data_loader.load_data(path=opt.test_path)

        train_examples.extend(dev_examples)
        train_examples.extend(test_examples)

        (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label) = \
            make_dict(opt, train_examples)
        logger.info(' fine-tune :: Finish train & dev & test prepare dict ')
        train_features = preprocessor.construct_feature(train_examples, train_max_support_size,
                                                        train_slot_label2id, train_slot_id2label,
                                                        train_intent_label2id, train_intent_id2label)
        logger.info(' fine-tune :: Finish prepare train & dev & test features ')
        if opt.do_debug:
            print('fine-tune :: train_slot_label2id: {}'.format(train_slot_label2id))
            print('fine-tune :: train_intent_label2id: {}'.format(train_intent_label2id))
            print('fine-tune :: train_examples: {} - {}'.format(len(train_examples), train_examples))
            print('fine-tune :: train_features: {} - {}'.format(len(train_features), train_features))
        if opt.save_feature:
            save_feature('ft_' + opt.train_path.replace('.json', '.saved.pk'),
                         train_features, train_slot_label2id, train_slot_id2label,
                         train_intent_label2id, train_intent_id2label)
    return train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label)


def main():
    """ to start the experiment """
    ''' set option '''
    parser = argparse.ArgumentParser()
    parser = define_args(parser, basic_args, train_args, test_args, preprocess_args, model_args)
    opt = parser.parse_args()
    print('Args:\n', json.dumps(vars(opt), indent=2))
    opt = option_check(opt)

    ''' device & environment '''
    device, n_gpu = set_device_environment(opt)
    os.makedirs(opt.output_dir, exist_ok=True)
    logger.info("Environment: device {}, n_gpu {}".format(device, n_gpu))

    ''' data & feature '''
    data_loader = FewShotRawDataLoader(opt)
    preprocessor = make_preprocessor(opt)
    if opt.do_train:
        train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label), \
            dev_features, (dev_slot_label2id, dev_slot_id2label), (dev_intent_label2id, dev_intent_id2label) = \
            get_training_data_and_feature(opt, data_loader, preprocessor)

        if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
            opt.train_label_mask = make_label_mask(opt, opt.train_path, train_slot_label2id)
            opt.dev_label_mask = make_label_mask(opt, opt.dev_path, dev_slot_label2id)
    else:
        train_features, train_slot_label2id, train_slot_id2label, train_intent_label2id, train_intent_id2label, \
            dev_features, dev_slot_label2id, dev_slot_id2label, dev_intent_label2id, dev_intent_id2label = [None] * 10
        if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
            opt.train_label_mask = None
            opt.dev_label_mask = None

    if opt.do_predict:
        test_features, (test_slot_label2id, test_slot_id2label), (test_intent_label2id, test_intent_id2label) = get_testing_data_feature(opt, data_loader, preprocessor)
        if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
            opt.test_label_mask = make_label_mask(opt, opt.test_path, test_slot_label2id)
    else:
        test_features, test_slot_label2id, test_slot_id2label, test_intent_label2id, test_intent_id2label = [None] * 6
        if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
            opt.test_label_mask = None

    ''' over fitting test '''
    if opt.do_overfit_test:
        test_features, (test_slot_label2id, test_slot_id2label), (test_intent_label2id, test_intent_id2label) = \
            train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label)
        dev_features, (dev_slot_label2id, dev_slot_id2label), (dev_intent_label2id, dev_intent_id2label) = \
            train_features, (train_slot_label2id, train_slot_id2label), (train_intent_label2id, train_intent_id2label)

    train_id2label_map = {'slot': train_slot_id2label, 'intent': train_intent_id2label}
    dev_id2label_map = {'slot': dev_slot_id2label, 'intent': dev_intent_id2label}
    test_id2label_map = {'slot': test_slot_id2label, 'intent': test_intent_id2label}

    ''' select training & testing mode '''
    trainer_class = SchemaFewShotTrainer if opt.use_schema else FewShotTrainer
    tester_class = SchemaFewShotTester if opt.use_schema else FewShotTester

    ''' training '''
    best_model = None
    if opt.do_train:
        logger.info("***** Perform training *****")
        if opt.restore_cpt:  # restart training from a check point.
            training_model = load_model(opt.saved_model_path)  # restore optimizer param is not support now.
            opt = training_model.opt
            opt.warmup_epoch = -1
        else:
            training_model = make_model(opt, config={
                # 'num_tags': len(train_slot_label2id) if opt.task in ['slot_filling', 'slu'] else 0,
                'num_tags': {'slot': len(train_slot_label2id), 'intent': len(train_intent_label2id)},
                'id2label': train_id2label_map})

        # ================== fine-tune =====================
        if opt.finetune and not opt.restore_cpt:
            logger.info("***** Start fine-tuning target domain with only support data *****")
            # train & dev as fine-tune train
            # test as fine-tune dev
            ft_preprocessor = make_preprocessor(opt, finetune=opt.finetune)

            if opt.ft_dataset == 'origin':
                ft_train_features, (ft_train_slot_label2id, ft_train_slot_id2label), \
                    (ft_train_intent_label2id, ft_train_intent_id2label) = get_training_data_feature(
                        opt, data_loader, ft_preprocessor)
                ft_test_features, (ft_test_slot_label2id, ft_test_slot_id2label), \
                    (ft_test_intent_label2id, ft_test_intent_id2label) = get_testing_data_feature(
                    opt, data_loader, ft_preprocessor)
            elif opt.ft_dataset == 'shuffle':
                ft_features, (ft_train_slot_label2id, ft_train_slot_id2label), \
                    (ft_train_intent_label2id, ft_train_intent_id2label) = get_support_data_feature(
                        opt, data_loader, ft_preprocessor)
                (ft_test_slot_label2id, ft_test_slot_id2label), (ft_test_intent_label2id, ft_test_intent_id2label) = \
                    (ft_train_slot_label2id, ft_train_slot_id2label), (ft_train_intent_label2id, ft_train_intent_id2label)

                random.seed(opt.seed)
                random.shuffle(ft_features)

                train_num = int(len(ft_features) * opt.ft_td_rate)

                ft_train_features, ft_test_features = ft_features[:train_num], ft_features[train_num:]

            else:
                raise NotImplementedError

            ft_label2id = {'slot': ft_train_slot_label2id, 'intent': ft_train_intent_label2id}
            ft_id2label = {'slot': ft_train_slot_id2label, 'intent': ft_train_intent_id2label}

            ft_test_id2label = {'slot': ft_test_slot_id2label, 'intent': ft_test_intent_id2label}

            finetune_model = make_finetune_model(opt, config={'label2id': ft_label2id,
                                                              'id2label': ft_id2label})
            finetune_model = prepare_model(opt, finetune_model, device, n_gpu)
            ft_upper_structures = ['intent', 'slot']
            ft_param_to_optimize, ft_optimizer, ft_scheduler = prepare_optimizer(
                opt, finetune_model, len(ft_train_features), ft_upper_structures)

            ft_tester = FineTuneTester(opt, device, n_gpu)
            ft_trainer = FineTuneTrainer(opt, ft_optimizer, ft_scheduler, ft_param_to_optimize, device, n_gpu,
                                         tester=ft_tester)

            ft_trained_model, ft_best_dev_score, ft_test_score = ft_trainer.do_train(
                finetune_model, ft_train_features, opt.ft_num_train_epochs, ft_test_features, ft_test_id2label)

            print('========== Fine-tuning finished! ==========')

            # ============ init embedder parameters to training_model ===========
            training_model = prepare_model(opt, training_model, device, n_gpu)
            if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
                training_model.label_mask = opt.train_label_mask.to(device)
            # prepare a set of name subseuqence/mark to use different learning rate for part of params

            training_model.context_embedder.embedder.load_state_dict(
                ft_trained_model.context_embedder.embedder.state_dict())

            # remove saved model file
            all_cpt_file = list(filter(lambda x: '.cpt.pl' in x, os.listdir(opt.output_dir)))
            for cpt_file in all_cpt_file:
                os.unlink(os.path.join(opt.output_dir, cpt_file))

        else:
            training_model = prepare_model(opt, training_model, device, n_gpu)
            if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
                training_model.label_mask = opt.train_label_mask.to(device)
            # prepare a set of name subseuqence/mark to use different learning rate for part of params

        upper_structures = [
            'backoff', 'scale_rate', 'f_theta', 'phi', 'start_reps', 'end_reps', 'biaffine', 'relation']
        metric_params = ['intent', 'slot', 'metric', 'slu_rnn_encoder']
        if not opt.no_up_metric_params:
            upper_structures.extend(metric_params)
        param_to_optimize, optimizer, scheduler = prepare_optimizer(
            opt, training_model, len(train_features), upper_structures)
        tester = tester_class(opt, device, n_gpu)
        trainer = trainer_class(opt, optimizer, scheduler, param_to_optimize, device, n_gpu, tester=tester)
        if opt.warmup_epoch > 0:
            training_model.no_embedder_grad = True
            stage_1_param_to_optimize, stage_1_optimizer, stage_1_scheduler = prepare_optimizer(
                opt, training_model, len(train_features), upper_structures)
            stage_1_trainer = trainer_class(opt, stage_1_optimizer, stage_1_scheduler, stage_1_param_to_optimize, device, n_gpu, tester=None)
            trained_model, best_dev_score, test_score = stage_1_trainer.do_train(
                training_model, train_features, opt.warmup_epoch)
            training_model = trained_model
            training_model.no_embedder_grad = False
            print('========== Warmup training finished! ==========')
        trained_model, best_dev_score, test_score = trainer.do_train(
            training_model, train_features, opt.num_train_epochs,
            dev_features, dev_id2label_map, test_features, test_id2label_map, best_dev_score_now=0)

        # decide the best model
        if not opt.eval_when_train:  # select best among check points
            best_model, best_score, test_score_then = trainer.select_model_from_check_point(
                train_id2label_map, dev_features, dev_id2label_map, test_features, test_id2label_map,
                rm_cpt=opt.delete_checkpoint)
        else:  # best model is selected during training
            best_model = trained_model
        logger.info('dev:{}, test:{}'.format(best_dev_score, test_score))
        print('dev:{}, test:{}'.format(best_dev_score, test_score))

    ''' testing '''
    if opt.do_predict:
        logger.info("***** Perform testing *****")
        print("***** Perform testing *****")
        tester = tester_class(opt, device, n_gpu)
        if not best_model:  # no trained model load it from disk.
            if not opt.saved_model_path or not os.path.exists(opt.saved_model_path):
                raise ValueError("No model trained and no trained model file given (or not exist)")
            if os.path.isdir(opt.saved_model_path):  # eval a list of checkpoints
                max_score = eval_check_points(opt, tester, test_features, test_id2label_map, device)
                print('best check points scores:{}'.format(max_score))
                exit(0)
            else:
                best_model = load_model(opt.saved_model_path)

        ''' test the best model '''
        testing_model = tester.clone_model(best_model, test_id2label_map)  # copy reusable params
        if opt.mask_transition and opt.task in ['slot_filling', 'slu']:
            testing_model.label_mask = opt.test_label_mask.to(device)
        test_score = tester.do_test(testing_model, test_features, test_id2label_map, log_mark='test_pred')
        logger.info('test:{}'.format(test_score))
        print('test:{}'.format(test_score))


if __name__ == "__main__":
    main()
