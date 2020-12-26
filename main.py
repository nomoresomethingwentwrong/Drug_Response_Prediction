def warn(*args, **kwargs):
    pass
import warnings
warnings.warn = warn


from model import Net, Net_CNN
import os
from datasets import *
import torch.optim
import torch.nn as nn
import numpy as np
import time
import argparse
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score, f1_score

torch.manual_seed(5)
torch.cuda.manual_seed(5)
torch.cuda.manual_seed_all(5)  # if you are using multi-GPU.
np.random.seed(5)  # Numpy module.
# random.seed(10)  # Python random module.
torch.manual_seed(5)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True


parser = argparse.ArgumentParser(description='Drug Response Prediction')
parser.add_argument('--batchSize', type=int, default=32, help='input batch size')
parser.add_argument('--epoch', type=int, default=500, help='number of epochs')
parser.add_argument('--lr', type=float, default=0.01, help='initial learning rate')
parser.add_argument('--esthres', type=int, default=10, help='')
# parser.add_argument('--est', type=int, default=30, help='early_stopping_threshold')

parser.add_argument('--checkpoint', type=str, default=None, help='path/to/checkpoint.pth.tar')
parser.add_argument('--data', type=str, default='RPPA', help='')
parser.add_argument('--model', type=str, default='Net', help='')
parser.add_argument('--expr_dir', type=str, default="experiments/", help='path/to/save_dir')
parser.add_argument('--cv', action='store_true', help='cross validation') #--cv
# parser.add_argument('--num_param', type=int, default =101)
parser.add_argument('--out_embed', type=int, default=200)
parser.add_argument('--out_lay2', type=int, default =128)
parser.add_argument('--out_lay3', type=int, default =64)
parser.add_argument('--output_dim',type=int, default=24)
# num_parameter,out_embedding=200,out_layer2=128,out_layer3=32,output_dim=22

def calc_r2 (x,y):
    total = 0
    for i in range(24):
        total += r2_score(x[:,i],y[:,i])
    total /= 24
    return total

def calc_accuracy(x,y):
    correct = np.sum(x == y)
    total = len(x)
    accuracy = (correct*100/total)

    return accuracy

def top_k(x,y):
    total = len(x)
    correct = 0
    for i in range(len(x)):
        if(x[i] in y[i].numpy()): #if pred in top actual values
            correct += 1
    topkaccuracy = (correct*100/total)
    return topkaccuracy


def main(args, train_data, valid_data, test_data,train_label, valid_label, test_label):
    ### init training and val stuff ##
    #Loss Function
    criterion = nn.MSELoss()

    args.is_cuda = torch.cuda.is_available()
    #Instantiate model class
    if args.model == 'Net':
        model = Net(args)     #force model to float and cuda
    elif args.model == 'Net_CNN':
        model = Net_CNN(args)
    #Tell Pytorch to run the code on the GPU
    if args.is_cuda:
        model = model.cuda()

    #Adam optimizer
    optimizer = torch.optim.Adam(model.parameters(), args.lr, weight_decay=0)

    train_loader = torch.utils.data.DataLoader(TensorDataset(torch.tensor(train_data),torch.tensor(train_label)), batch_size=args.batchSize, shuffle = True,num_workers=0, pin_memory=True)
    test_loader = torch.utils.data.DataLoader(TensorDataset(torch.tensor(test_data), torch.tensor(test_label)), batch_size=args.batchSize, shuffle = True, num_workers=0, pin_memory=True)
    val_loader = torch.utils.data.DataLoader(TensorDataset(torch.tensor(valid_data),torch.tensor(valid_label)), batch_size=args.batchSize, shuffle = True, num_workers=0, pin_memory=True)


    all_train_loss, all_valid_loss, all_test_loss = [],[],[]
    all_train_TT = []
    all_train_r_square= []
    all_valid_r_square =[]
    all_test_r_square =[]

    #For Early Stopping
    best_valid_loss = 99999
    test_loss_best_val = 99999
    test_rsquare_best_valid = 0

    count = 0

    for epoch in range(0,args.epoch):

        # train for one epoch
        # returns total_loss, TT and r2 for 1 epoch
        epoch_total_loss, TT, r_square_train = train(train_loader, model, criterion, optimizer, epoch, args)

        #loss,r2 and TT for total epochs
        all_train_loss.append(epoch_total_loss)
        all_train_r_square.append(r_square_train)
        all_train_TT.append(TT)

        # evaluate on validation set
        epoch_val_loss, r_square_val = validate(val_loader, model, criterion, args)
        all_valid_loss.append(epoch_val_loss)
        all_valid_r_square.append(r_square_val )

        # evaluate on test set
        epoch_test_loss, r_square_test = validate(test_loader, model, criterion, args, test_flag =True)
        all_test_loss.append(epoch_test_loss)
        all_test_r_square.append(r_square_test )

        #Early Stopping
        state = {
            'epoch': epoch + 1,
            'state_dict': model.state_dict()
        }
        if(epoch_val_loss < best_valid_loss):
            count = 0
            best_valid_loss = epoch_val_loss
            test_loss_best_val = epoch_test_loss
            test_r_square_best_valid = r_square_test

            save_checkpoint(state, True, args)
        else:
            count = count + 1
            if(count >= args.esthres):
                break
    #Calc mean r_square
    avg_test_r_square = np.mean(all_test_r_square)
    avg_valid_r_square = np.mean(all_valid_r_square)
    avg_train_r_square = np.mean(all_train_r_square)
    #Calc std r_square
    std_test_r_square = np.std(all_test_r_square)
    std_valid_r_square = np.std(all_valid_r_square)
    std_train_r_square = np.std(all_train_r_square)

    #plotting the training and validation loss
    plt.clf() #clear
    plt.plot(all_train_loss, label='Training loss')
    plt.plot(all_valid_loss, label='Validation loss')
    plt.title('Model loss')
    plt.ylabel('loss')
    plt.xlabel('No. of epochs')
    plt.legend(['train', 'test'], loc='upper right')
    plt.savefig(os.path.join(args.expr_dir, 'Exp_graph.png'))

    return best_valid_loss, test_loss_best_val, avg_test_r_square, std_test_r_square

def train(train_loader, model, criterion, optimizer, epoch, args):
    total_loss = 0.0
    # switch to train mode
    model.train()

    pred_values = np.empty((0,24))
    target_values = np.empty((0,24))
    stime = time.time()

    #Updating the parameters each iteration. (# of iterations = # batches)
    #Each iteration: 1)Forward Propogation 2)Compute Costs 3)Backpropagation 4)Update parameters
    for i, (input, target) in enumerate(train_loader):
        # measure data loading time
        target = target.float()
        input = input.float()

        if args.is_cuda:
            target = target.cuda()
            input = input.cuda()

        #Forward pass to compute predicted output
        output = model(input) #bsx24
        #storing predicted and target values
        pred_values=np.concatenate((pred_values,output.cpu().detach().numpy()), axis=0)
        target_values = np.concatenate((target_values,target.cpu().detach().numpy()) ,axis=0)
        #Calculate Loss: MSE
        loss = criterion(output, target)
        #Adding loss for current iteration into total_loss
        total_loss += loss
        #Clear gradients w.r.t parameters
        optimizer.zero_grad()
        #Getting gradients w.r.t parameters
        loss.backward()
        #Updating parameters
        optimizer.step()
    #Time taken for 1 epoch
    TT = time.time() -stime
    #Avg. total_loss for all the iteration/loss for 1 epoch
    total_loss =  total_loss/(i+1)
    #calc r2
    r_square =  calc_r2(pred_values, target_values)
    #Find best drug
    best_drug_target = np.argmin(target_values, axis = -1)
    best_drug_predicted = np.argmin(pred_values, axis = -1)
    #Find top 3 drugs
    best_drug_target_top3 = torch.topk(torch.tensor(target_values), k=3, largest = False, dim=-1)[1]


    accuracy = calc_accuracy(best_drug_target,best_drug_predicted)
    topkaccuracy = top_k(best_drug_predicted, best_drug_target_top3)
    f1 = f1_score(best_drug_predicted,best_drug_target, average = 'micro')


    if args.verbose:
        print('Epoch: [{0}]\t'
          'Training Loss {loss:.3f}\t'
          'Time: {time:.2f}\t'
          'r_square: {r2}\t'
          'accuracy: {acc}\t'
          'topkaccuracy:{kacc}\t'
          'f1_score: {f1}'.format(
           epoch, loss=total_loss, time= TT, r2=r_square, acc=accuracy, kacc = topkaccuracy, f1 = f1))



    return total_loss, TT, r_square

def validate(val_loader, model, criterion, args, test_flag=False):

    # switch to evaluate mode
    model.eval()

    total_loss = 0.0
    pred_values = np.empty((0,24))
    target_values = np.empty((0,24))
    #Turn off gradients computation
    with torch.no_grad():

        for i, (input, target) in enumerate(val_loader):

            target = target.float()
            input = input.float()
            if args.is_cuda:
                target = target.cuda()
                input = input.cuda()

            # Forward pass to compute output
            output = model(input)
            pred_values=np.concatenate((pred_values,output.cpu().detach().numpy()), axis=0)
            target_values = np.concatenate((target_values,target.cpu().detach().numpy()) ,axis=0)
            #Calculate Loss: MSE
            loss = criterion(output, target)
            total_loss += loss

    total_loss =  total_loss/(i+1)
    r_square =  calc_r2(pred_values, target_values)

    #print options
    if test_flag:
        txt = 'Test'
    else:
        txt = 'Val'

    if args.verbose:
        print('{type}: \t'
          'Loss {loss:.4f}\t'.format(type=txt,loss=total_loss))

    return total_loss, r_square

def save_checkpoint(state, is_best, args, filename='checkpoint.pth.tar'):
    torch.save(state, os.path.join(args.expr_dir, filename))
    if is_best:
        torch.save(state, os.path.join(args.expr_dir, 'model_best.pth.tar'))


if __name__ == '__main__':
    args = parser.parse_args()
    #1) data loading
    if args.data == 'RPPA':
        if args.cv:
            train_val_data, train_val_label, test_data, test_label = read_RPPA(cv=args.cv)
        else:
            train_data, train_label, valid_data, valid_label, test_data, test_label = read_RPPA(cv=args.cv)
        args.num_param = 101

    elif args.data == 'Meta':
        if args.cv:
            train_val_data, train_val_label, test_data, test_label = read_Meta(cv=args.cv)
        else:
            train_data, train_label, valid_data, valid_label, test_data, test_label = read_Meta(cv=args.cv)
        args.num_param = 80

    elif args.data == 'Mut':
        if args.cv:
            train_val_data, train_val_label, test_data, test_label = read_Mutations(cv=args.cv)
        else:
            train_data, train_label, valid_data, valid_label, test_data, test_label = read_Mutations(cv=args.cv)
        args.num_param = 1040

    elif args.data == 'CNV':
        if args.cv:
            train_val_data, train_val_label, test_data, test_label = read_CNV(cv=args.cv)
        else:
            train_data, train_label, valid_data, valid_label, test_data, test_label = read_CNV(cv=args.cv)
        args.num_param = 88

    elif args.data == 'Exp':
        if args.cv:
            train_val_data, train_val_label, test_data, test_label = read_Expression(cv=args.cv)
        else:
            train_data, train_label, valid_data, valid_label, test_data, test_label = read_Expression(cv=args.cv)
        args.num_param = 616

    elif args.data == 'miRNA':
        if args.cv:
            train_val_data, train_val_label, test_data, test_label = read_miRNA(cv=args.cv)
        else:
            train_data, train_label, valid_data, valid_label, test_data, test_label = read_miRNA(cv=args.cv)
        args.num_param = 197

    #print options
    if args.cv:
        args.verbose = False
    else:
        args.verbose = True

    if args.cv:
        #2) Perform kfold cross-validation
        kf = KFold(n_splits=3)
        kf.get_n_splits(train_val_data)

        best_valid_results = []
        test_loss_best_val_results = []
        test_r_square_cv = []
        std_test_r_square_cv = []

        #In this case text_index is my val_index
        for train_index, test_index in kf.split(train_val_data):

            # print(train_index)
            # print(test_index)

            train_data, val_data = train_val_data[train_index], train_val_data[test_index]
            train_label, val_label = train_val_label[train_index], train_val_label[test_index]

            best_valid_loss, test_loss_best_val, avg_test_r_square, std_test_r_square = main(args, train_data, val_data, test_data, train_label, val_label, test_label)

            best_valid_results.append(best_valid_loss)
            test_loss_best_val_results.append(test_loss_best_val)
            test_r_square_cv.append(avg_test_r_square)
            std_test_r_square_cv.append(std_test_r_square)

        #Get avg. scores obtained across the k-folds
        best_valid_average = np.mean(best_valid_results)
        test_loss_best_val_average = np.mean(test_loss_best_val_results)
        test_r2_average_cv = np.mean(test_r_square_cv)
        test_r2_std_cv = np.mean(std_test_r_square_cv)

        print("best_valid_loss_CV_avg:", best_valid_average,  "test_loss_best_val_CV_avg:", test_loss_best_val_average,"best_test_r2_average:", test_r2_average_cv, "best_test_r2_std:", test_r2_std_cv)
    else:
        best_valid_loss, test_loss_best_val, avg_test_r_square,std_test_r_square = main(args, train_data, valid_data, test_data, train_label, valid_label, test_label)
        print("best_valid_loss:", best_valid_loss,  "test_loss_best_val:", test_loss_best_val, "best_test_r2_average:", avg_test_r_square, "best_test_r2_std:", std_test_r_square)
