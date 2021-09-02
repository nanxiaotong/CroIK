# 更换的是注意力所在resnet的位置

from __future__ import absolute_import

'''Resnet for cifar dataset.
Ported form
https://github.com/facebook/fb.resnet.torch
and
https://github.com/pytorch/vision/blob/master/torchvision/models/resnet.py
(c) YANG, Wei
'''
from torch.nn import init
import torch
import torch.nn as nn
import torch.nn.functional as F
import math


def conv3x3(in_planes, out_planes, stride=1):
    "3x3 convolution with padding"
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)

def weights_init_classifier(m):
    classname = m.__class__.__name__
    if classname.find('Linear') != -1:
        init.normal(m.weight.data, std=0.001)
        init.constant(m.bias.data, 0.0)

def weights_init_kaiming(m):
    classname = m.__class__.__name__
    # print(classname)
    if classname.find('Conv') != -1:
        init.kaiming_normal(m.weight.data, a=0, mode='fan_in')
    elif classname.find('Linear') != -1:
        init.kaiming_normal(m.weight.data, a=0, mode='fan_out')
        init.constant(m.bias.data, 0.0)
    elif classname.find('BatchNorm1d') != -1:
        init.normal(m.weight.data, 1.0, 0.02)
        init.constant(m.bias.data, 0.0)

class ChannelAttention(nn.Module):
    def __init__(self, in_planes, ratio=16):
        super(ChannelAttention, self).__init__()
        # print("--------------ca------------"+ str(in_planes))
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)
           
        self.fc = nn.Sequential(nn.Conv2d(in_planes, in_planes // 16, 1, bias=False),
                               nn.ReLU(),
                               nn.Conv2d(in_planes // 16, in_planes, 1, bias=False))
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = self.fc(self.avg_pool(x))
        max_out = self.fc(self.max_pool(x))
        out = avg_out + max_out
        scale = self.sigmoid(out)
        return scale

class SpatialAttention(nn.Module):
    def __init__(self, kernel_size=7):
        super(SpatialAttention, self).__init__()

        self.conv1 = nn.Conv2d(2, 1, kernel_size, padding=kernel_size//2, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = torch.mean(x, dim=1, keepdim=True)
        max_out, _ = torch.max(x, dim=1, keepdim=True)
        x = torch.cat([avg_out, max_out], dim=1)
        x = self.conv1(x)
        scale = self.sigmoid(x)
        return scale

# 用于ResNet18和34的残差块，用的是2个3x3的卷积
class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(BasicBlock, self).__init__()
        self.conv1 = conv3x3(inplanes, planes, stride)
        self.bn1 = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = conv3x3(planes, planes)
        self.bn2 = nn.BatchNorm2d(planes)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out

class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride,
                               padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(planes, planes * 4, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(planes * 4)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out

class ResNet(nn.Module):
    def __init__(self, depth, num_classes=1000):
        super(ResNet, self).__init__()
        # Model type specifies number of layers for CIFAR-10 model
        assert (depth - 2) % 6 == 0, 'depth should be 6n+2'
        n = (depth - 2) // 6
        #block = Bottleneck if depth >=44 else BasicBlock
        block = BasicBlock
        self.inplanes = 16
        self.conv1 = nn.Conv2d(3, 16, kernel_size=3, padding=1,
                               bias=False)
        self.bn1 = nn.BatchNorm2d(16)
        self.relu = nn.ReLU(inplace=True)
        self.layer1 = self._make_layer(block, 16, n)
        self.layer2 = self._make_layer(block, 32, n, stride=2)
        self.layer3 = self._make_layer(block, 64, n, stride=2)
        self.avgpool = nn.AvgPool2d(8)
        self.fc = nn.Linear(64 * block.expansion, num_classes)
        
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes))
        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)    # 32x32
        x = self.layer1(x)  # 32x32
        x = self.layer2(x)  # 16x16
        x = self.layer3(x)  # 8x8
        x = self.avgpool(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x

class FFL_ResNet(nn.Module):

    def __init__(self, depth, num_classes=1000):
        super(FFL_ResNet, self).__init__()
        # Model type specifies number of layers for CIFAR-10 model
        assert (depth - 2) % 6 == 0, 'depth should be 6n+2'
        n = (depth - 2) // 6

        #block = Bottleneck if depth >=44 else BasicBlock
        # if depth >= 44:
        #     block = Bottleneck
        #     print("Bottleneck depth :"+ str(depth))
        # else:
        #     block = BasicBlock
        #     print("BasicBlock depth :"+ str(depth))

        block = BasicBlock
        self.inplanes = 16
        self.conv1 = nn.Conv2d(3, 16, kernel_size=3, padding=1,
                               bias=False)
        self.bn1 = nn.BatchNorm2d(16)
        self.relu = nn.ReLU(inplace=True)

        # # 网络的卷积层的第一层加入注意力机制
        self.ca = ChannelAttention(self.inplanes)
        self.sa = SpatialAttention()

        self.layer1_1 = self._make_layer(block, 16, n)
        self.layer1_2 = self._make_layer(block, 16, n)

        fix_inplanes=self.inplanes
        self.layer2_1 = self._make_layer(block, 32, n, stride=2)
        self.inplanes = fix_inplanes  ##reuse self.inplanes
        self.layer2_2 = self._make_layer(block, 32, n, stride=2)
        fix_inplanes=self.inplanes
        self.layer3_1 = self._make_layer(block, 64, n, stride=2)
        self.inplanes = fix_inplanes  ##reuse self.inplanes
        self.layer3_2 = self._make_layer(block, 64, n, stride=2)

        # 网络的卷积层的最后一层加入注意力机制
        self.ca1 = ChannelAttention(self.inplanes)
        self.sa1 = SpatialAttention()

        self.avgpool = nn.AvgPool2d(8)

        # 全连接层
        self.classfier3_1=nn.Linear(64 * block.expansion, num_classes)
        self.classfier3_2=nn.Linear(64 * block.expansion, num_classes)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes))

        return nn.Sequential(*layers)

    def forward(self, x):
        # residual = x
        fmap = []

        x_1 = self.conv1(x)
        x_1 = self.bn1(x_1)
        x_1 = self.relu(x_1)    # 32x32

        x_2 = self.conv1(x)
        x_2 = self.bn1(x_2)
        x_2 = self.relu(x_2)    # 32x32
        print("-----------------0------------------" + str(x_1.size()))
        print("-----------------0------------------" + str(x_2.size()))          
        # # 教师网络进行AM
        am = self.ca(x_2) * x_2
        am = self.sa(am)     
        
        cm = self.ca(x_1) * x_1
        cm = self.sa(cm) 
        # 如果不将传递给学生，仍为自身传递，即将细粒度信息与之前信息进行简单相加； x_3_2 = module_input * x_3_2; x_3_2 += residual
        # 如果将教师细粒度信息传递给学生，将空间注意力结果与学生网络输出进行点乘
        x_1 = x_1 * am
        x_2 = x_2 * cm
        print("-----------------1------------------" + str(x_1.size()))
        print("-----------------1------------------" + str(x_2.size()))          
        x_1_1 = self.layer1_1(x_1)  # 32x32
        x_1_2 = self.layer1_2(x_2)  # 32x32
        print("-----------------2------------------" + str(x_1_1.size()))
        print("-----------------2------------------" + str(x_1_2.size()))  
        x_2_1 = self.layer2_1(x_1_1)  # 16x16
        x_2_2 = self.layer2_2(x_1_2)  # 16x16
        print("-----------------3------------------" + str(x_2_1.size()))
        print("-----------------3------------------" + str(x_2_2.size()))  
        # 理解为学生网络
        x_3_1 = self.layer3_1(x_2_1)  # 8x8 
        # 理解为教师网络
        x_3_2 = self.layer3_2(x_2_2)     
        # 此时的x_3_1和x_3_2为最后一个block的输出
        print("-----------------4------------------" + str(x_3_1.size()))
        print("-----------------4------------------" + str(x_3_2.size()))          
        fmap.append(x_3_1)
        fmap.append(x_3_2)
        
        # 教师网络进行AM
        am1 = self.ca1(x_3_2) * x_3_2
        am2 = self.sa1(am1)     
        
        cm1 = self.ca1(x_3_1) * x_3_1
        cm2 = self.sa1(cm1) 
        # 如果不将传递给学生，仍为自身传递，即将细粒度信息与之前信息进行简单相加； x_3_2 = module_input * x_3_2; x_3_2 += residual
        # 如果将教师细粒度信息传递给学生，将空间注意力结果与学生网络输出进行点乘
        x_3_1 = x_3_1 * am2
        x_3_2 = x_3_2 * cm2
        
        x_3_1 = self.avgpool(x_3_1)
        x_3_1 = x_3_1.view(x_3_1.size(0), -1) # pytorch中view函数的作用为重构张量的维度，相当于numpy中resize()的功能
        x_3_2 = self.avgpool(x_3_2)
        x_3_2 = x_3_2.view(x_3_2.size(0), -1)

        # 此时的x_3_1和x_3_2为logits数据
        x_3_1 = self.classfier3_1(x_3_1)
        x_3_2 = self.classfier3_2(x_3_2)

        return x_3_1,x_3_2,fmap

class Fusion_module(nn.Module):
    def __init__(self,channel,numclass,sptial):
        super(Fusion_module, self).__init__()
        self.fc2   = nn.Linear(channel, numclass)
        self.conv1 =  nn.Conv2d(channel*2, channel*2, kernel_size=3, stride=1, padding=1, groups=channel*2, bias=False)
        self.bn1 = nn.BatchNorm2d(channel * 2)
        self.conv1_1 = nn.Conv2d(channel*2, channel, kernel_size=1, groups=1, bias=False)
        self.bn1_1 = nn.BatchNorm2d(channel)


        self.sptial = sptial


        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
        #self.avg = channel
    def forward(self, x,y):
        bias = False
        atmap = []
        input = torch.cat((x,y),1)

        x = F.relu(self.bn1((self.conv1(input))))
        x = F.relu(self.bn1_1(self.conv1_1(x)))

        atmap.append(x)
        x = F.avg_pool2d(x, self.sptial)
        x = x.view(x.size(0), -1)

        out = self.fc2(x)
        atmap.append(out)

        return out


class SelfCrossFcResnet(nn.Module):
    def __init__(self, depth, num_classes=1000):
        super(SelfCrossFcResnet, self).__init__()
        # Model type specifies number of layers for CIFAR-10 model
        assert (depth - 2) % 6 == 0, 'depth should be 6n+2'
        n = (depth - 2) // 6
        #block = Bottleneck if depth >=44 else BasicBlock
        block = BasicBlock
        self.inplanes = 16
        self.conv1_1 = nn.Conv2d(3, 16, kernel_size=3, padding=1,
                               bias=False)
        self.bn1_1 = nn.BatchNorm2d(16)
        self.conv1_2 = nn.Conv2d(3, 16, kernel_size=3, padding=1,
                               bias=False)
        self.bn1_2 = nn.BatchNorm2d(16)

        self.relu = nn.ReLU(inplace=True)

        '''
        self.layer1_1 = self._make_layer(block, 16, n)
        self.layer1_2 = self._make_layer(block, 16, n)

        fix_inplanes=self.inplanes
        self.layer2_1 = self._make_layer(block, 32, n, stride=2)
        self.inplanes = fix_inplanes  ##reuse self.inplanes
        self.layer2_2 = self._make_layer(block, 32, n, stride=2)
        fix_inplanes=self.inplanes
        self.layer3_1 = self._make_layer(block, 64, n, stride=2)
        self.inplanes = fix_inplanes  ##reuse self.inplanes
        self.layer3_2 = self._make_layer(block, 64, n, stride=2)
        '''


        blocksSize = [(32, 32), (32, 16), (16, 8)]
        channels = [16, 32, 64]
        strides = [1, 2, 2]
        self.net1Blocks = nn.ModuleList()
        self.net1CrossNet = nn.ModuleList()
        self.net2Blocks = nn.ModuleList()
        self.net2CrossNet = nn.ModuleList()
        for stage in range(3):
            bkplanes = self.inplanes
            self.net1Blocks.append(self._make_layer(block, channels[stage], n, strides[stage]))
            self.inplanes = bkplanes
            self.net2Blocks.append(self._make_layer(block, channels[stage], n, strides[stage]))
            stageCrossNet1 = nn.ModuleList()
            stageCrossNet2 = nn.ModuleList()
            for to in range(stage+1, 3):
                stageCrossNet1.append(self._make_fusion_layer(channels[stage], channels[to], blocksSize[stage][1], int(blocksSize[stage][1]/blocksSize[to][1])))
                stageCrossNet2.append(self._make_fusion_layer(channels[stage], channels[to], blocksSize[stage][1], int(blocksSize[stage][1]/blocksSize[to][1])))
            self.net1CrossNet.append(stageCrossNet1)
            self.net2CrossNet.append(stageCrossNet2)

        self.avgpool = nn.AvgPool2d(8)

        # 全连接层
        self.fc1=nn.Linear(64 * block.expansion, num_classes)
        self.fc2=nn.Linear(64 * block.expansion, num_classes)

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion),
            )

        layers = []
        layers.append(block(self.inplanes, planes, stride, downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes))
        return nn.Sequential(*layers)

    def _make_fusion_layer(self, in_planes, out_planes, in_size, minification):
        layers = []
        layers.append(nn.Conv2d(in_planes, out_planes, minification, minification, padding=0, bias=False))
        # layers.append(nn.AvgPool2d(minification, minification))
        layers.append(nn.BatchNorm2d(out_planes))
        layers.append(nn.ReLU(inplace=True))
        return nn.Sequential(*layers)

    def forward(self, x):
        x1 = self.conv1_1(x)
        x1 = self.bn1_1(x1)
        x1 = self.relu(x1)    # 32x32
        x2 = self.conv1_2(x)
        x2 = self.bn1_2(x2)
        x2 = self.relu(x2)    # 32x32
        
        fmap = []
        crossFusionKnowledge = []
        net1Knowledge = []
        net2Knowledge = []
        for stage in range(3):
            x1 = self.net1Blocks[stage](x1)
            x2 = self.net2Blocks[stage](x2)
            
            temp1 = x1
            temp2 = x2
            for preNum in range(0, stage):
                temp1 = temp1 + net1Knowledge[preNum][stage-preNum-1]
                temp2 = temp2 + net2Knowledge[preNum][stage-preNum-1]
            crossFusionKnowledge.append((torch.flatten(temp1,1), torch.flatten(temp2,1)))

            stageKnowledge1 = []
            stageKnowledge2 = []
            for to in range(stage+1, 3):
                stageKnowledge1.append(self.net1CrossNet[stage][to-stage-1](x1))
                stageKnowledge2.append(self.net2CrossNet[stage][to-stage-1](x2))
            net1Knowledge.append(stageKnowledge1)
            net2Knowledge.append(stageKnowledge2)

        
        fmap.append(x1)
        fmap.append(x2)



        x1 = self.avgpool(x1)
        x1 = x1.view(x1.size(0), -1)
        x1 = self.fc1(x1)
        x2 = self.avgpool(x2)
        x2 = x2.view(x2.size(0), -1)
        x2 = self.fc2(x2)
        return x1, x2, crossFusionKnowledge, fmap

def resnet(**kwargs):
    """
    Constructs a ResNet model.
    """
    return ResNet(**kwargs)


def cross_resnet(**kwargs):
    """
    Constructs a ResNet model.
    """
    return SelfCrossFcResnet(**kwargs)