import hashlib,json
import numpy as np
from sklearn.model_selection import StratifiedKFold
from sklearn.naive_bayes import GaussianNB
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix,accuracy_score,f1_score
from .domain_validation import validate_parameters
FEATURES=['rms','centroid','kurtosis']

def _fit(records,parameters):
    p=validate_parameters(parameters);data=[r['values'] for r in records]
    X=np.array([[r[f] for f in FEATURES] for r in data],float);y=np.array([r['label'] for r in data])
    labels,counts=np.unique(y,return_counts=True)
    if len(labels)<2 or min(counts)<p['folds']:raise ValueError('至少两种故障类型，且每类样本数不少于交叉验证折数')
    if len(data)<12:raise ValueError('分类研究至少需要12条样本')
    if np.all(np.var(X,axis=0)==0):raise ValueError('全部声学特征恒定，无法学习故障差异，请补充独立观测')
    scaler=StandardScaler().fit(X);model=GaussianNB(var_smoothing=p['smoothing']).fit(scaler.transform(X),y)
    return p,X,y,labels,scaler,model

def freeze_model(records,parameters,run_checksum):
    """Fit once on the frozen research snapshot and return a portable model definition.

    The definition only keeps the fitted Gaussian parameters so continuous monitoring
    cannot drift if the research snapshot or scikit-learn changes later.
    """
    p,X,y,labels,scaler,model=_fit(records,parameters)
    definition={'features':FEATURES,'classes':[str(c) for c in model.classes_],'priors':model.class_prior_.tolist(),
                'theta':model.theta_.tolist(),'var':model.var_.tolist(),'mean':scaler.mean_.tolist(),
                'scale':scaler.scale_.tolist(),'smoothing':p['smoothing'],'training_count':int(len(y)),
                'run_checksum':run_checksum}
    definition['checksum']=hashlib.sha256(json.dumps({k:definition[k] for k in sorted(definition)},sort_keys=True).encode()).hexdigest()
    return definition

def predict_frozen(definition,values):
    x=np.array([values[f] for f in definition['features']],float)
    scaled=(x-np.array(definition['mean'],float))/np.array(definition['scale'],float)
    theta=np.array(definition['theta'],float);var=np.array(definition['var'],float);priors=np.array(definition['priors'],float)
    log_joint=-.5*np.sum(np.log(2*np.pi*var)+(scaled-theta)**2/var,axis=1)+np.log(priors)
    top=log_joint.max();posterior=np.exp(log_joint-top);posterior/=posterior.sum()
    index=int(posterior.argmax())
    classes=definition['classes']
    return classes[index],float(posterior[index]),{c:float(v) for c,v in zip(classes,posterior)}


def calculate(records,parameters):
    p,X,y,labels,_,_=_fit(records,parameters)
    data=[r['values'] for r in records]
    splitter=StratifiedKFold(p['folds'],shuffle=True,random_state=42)
    counts=np.array([int((y==l).sum()) for l in labels])
    predictions=np.empty(len(y),dtype=y.dtype);probs=np.zeros((len(y),len(labels)));fold_results=[]
    for fold,(train,test) in enumerate(splitter.split(X,y),1):
        scaler=StandardScaler().fit(X[train]);model=GaussianNB(var_smoothing=p['smoothing']).fit(scaler.transform(X[train]),y[train])
        predictions[test]=model.predict(scaler.transform(X[test]));probs[test]=model.predict_proba(scaler.transform(X[test]))
        fold_results.append({'fold':fold,'training':len(train),'validation':len(test),'accuracy':float(accuracy_score(y[test],predictions[test])),'training_indices':train.tolist(),'validation_indices':test.tolist(),'training_mean':scaler.mean_.tolist(),'class_priors':model.class_prior_.tolist()})
    matrix=confusion_matrix(y,predictions,labels=labels).tolist()
    rows=[{'reference':records[i]['reference'],'actual':str(y[i]),'predicted':str(predictions[i]),'posterior':float(probs[i].max())} for i in range(len(y))]
    return {'summary':[{'label':'交叉验证准确率','value':float(accuracy_score(y,predictions))},{'label':'宏平均 F1','value':float(f1_score(y,predictions,average='macro'))},{'label':'样本数','value':len(y)},{'label':'类型数','value':len(labels)}], 'labels':labels.tolist(),'confusion_matrix':matrix,'folds':fold_results,'rows':rows,'columns':['reference','actual','predicted','posterior'],'chart':[{'label':str(l),'value':int(c)} for l,c in zip(labels,counts)],'explanation':'全部预测均为折外预测；模型后验未做校准，不能当作检修正确率保证。','checksum':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),'seed':42}
