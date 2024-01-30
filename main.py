import numpy as np
import pandas as pd

import lasio
from scipy import linalg, optimize
import matplotlib.pyplot as plt

import torch

class ARI:
    def __init__(self):
        self.verbose     = True
        self.save_data   = True
        self.return_data = True

        self.method     = 'L-BFGS-B'
        self.lambda_reg = 1e-4
        self.tolerance  = 1e-3
        self.maxiter    = 100
        self.x0         = [0.5, 1.5]
        self.Wd_matrix  = True

        self.n_ensemble = 100
        self.noise_lvl  = 10

        self.check_torch_gpu()

    def check_torch_gpu(self):
        '''
        Check if Torch is successfully built with GPU support
        '''
        torch_version, cuda_avail = torch.__version__, torch.cuda.is_available()
        count, name = torch.cuda.device_count(), torch.cuda.get_device_name()
        if self.verbose:
            print('\n'+'-'*60)
            print('----------------------- VERSION INFO -----------------------')
            print('Torch version: {} | Torch Built with CUDA? {}'.format(torch_version, cuda_avail))
            print('# Device(s) available: {}, Name(s): {}'.format(count, name))
            print('-'*60+'\n')
        return None

    def load_data(self):
        column_names = ['AT10', 'AT30', 'AT60', 'AT90', 'GR', 'Rv', 'Rh']
        index_name   = 'DEPTH'
        # well 1
        well1 = lasio.read('well1.las').df()
        case1 = well1[['AT10','AT30','AT60','AT90','GR','RV72H_1D', 'RH72H_1D']].dropna()
        case1.columns = column_names
        case1.index.name = index_name
        # well 2
        well2 = lasio.read('well2.LAS').df()
        case2 = well2[['AT10','AT30','AT60','AT90','HCGR','RV72_1DF','RH72_1DF']].dropna()
        case2.columns = column_names
        case2.index.name = index_name
        return case1, case2
    
    def plot_curve(self, ax, df, curve, lb=None, ub=None, color='k', pad=0, s=2, mult=1,
                units:str=None, mask=None, offset:int=0, title:str=None, label:str=None,
                semilog:bool=False, bar:bool=False, fill:bool=None, rightfill:bool=False,
                marker=None, edgecolor=None, ls=None, alpha=None):
            if mask is None:
                x, y = -offset+mult*df[curve], df.index
            else:
                x, y = -offset+mult*df[curve][mask], df.index[mask]
            lb = x[~np.isnan(x)].min() if lb is None else lb
            ub = x[~np.isnan(x)].max() if ub is None else ub
            if semilog:
                ax.semilogx(x, y, c=color, label=curve, alpha=alpha,
                            marker=marker, markersize=s, markeredgecolor=edgecolor, linestyle=ls, linewidth=s)
            else:
                if bar:
                    ax.barh(y, x, color=color, label=curve, alpha=alpha)
                else:
                    ax.plot(x, y, c=color, label=curve, alpha=alpha,
                            marker=marker, markersize=s, markeredgecolor=edgecolor, linewidth=s, linestyle=ls)
            if fill:
                if rightfill:
                    ax.fill_betweenx(y, x, ub, alpha=alpha, color=color)
                else:
                    ax.fill_betweenx(y, lb, x, alpha=alpha, color=color)
            if units is None:
                if hasattr(df, 'curvesdict'):
                    units = df.curvesdict[curve].unit
                else:
                    units = ''
            ax.set_xlim(lb, ub)
            ax.grid(True, which='both')
            ax.set_title(title, weight='bold') if title != None else None
            xlab = label if label is not None else curve
            if offset != 0:
                ax.set_xlabel('{} [{}] with {} offset'.format(xlab, units, offset), color=color, weight='bold')
            else:
                ax.set_xlabel('{} [{}]'.format(xlab, units), color=color, weight='bold')
            ax.xaxis.set_label_position('top'); ax.xaxis.set_ticks_position('top')
            ax.xaxis.set_tick_params(color=color, width=s)
            ax.spines['top'].set_position(('axes', 1+pad/100))
            ax.spines['top'].set_edgecolor(color); ax.spines['top'].set_linewidth(2)
            if ls is not None:
                ax.spines['top'].set_linestyle(ls)
            return None
    
    def resistivity_inversion(self, df, Rvsh=None, Rhsh=None):
        if Rvsh is None:
            Rvsh = df['Rv'].iloc[np.argmax(df['GR'])]
        if Rhsh is None:
            Rhsh = df['Rh'].iloc[np.argmax(df['GR'])]
        df['Csh_lin'] = (df['GR'] - df['GR'].min()) / (df['GR'].max() - df['GR'].min())
        def objective(variables, *args):
            Csh, Rs = variables
            Rv,  Rh = args[0], args[1]
            eq1 = (Csh*Rvsh + (1-Csh)*Rs) - Rv
            eq2 = (Csh/Rhsh + (1-Csh)/Rs) - (1/Rh)
            eqs = [eq1/Rv, eq2*Rh] if self.Wd_matrix else [eq1, eq2]
            return linalg.norm(eqs) + self.lambda_reg*linalg.norm(variables)
        def inversion():
            res_aniso = df[['Rv','Rh']]
            sol, fun, jac, nfev = [], [], [], []
            for _, row in res_aniso.iterrows():
                Rv_value, Rh_value = row['Rv'], row['Rh']
                solution = optimize.minimize(objective,
                                            x0      = self.x0,
                                            args    = (Rv_value, Rh_value),
                                            bounds  = [(0,1), (None,None)],
                                            method  = self.method,
                                            tol     = self.tolerance,
                                            options = {'maxiter':self.maxiter})
                fun.append(solution.fun); jac.append(solution.jac); nfev.append(solution.nfev)
                jac1, jac2 = np.array(jac)[:,0], np.array(jac)[:,1]
                sol.append({'Rv':Rv_value, 'Rh':Rh_value, 'Csh':solution.x[0], 'Rs':solution.x[1]})
            sol = pd.DataFrame(sol, index=res_aniso.index)
            sol['fun'], sol['nfev'], sol['jac1'], sol['jac2'], sol['norm_jac'] = fun, nfev, jac1, jac2, linalg.norm(jac, axis=1)
            return sol
        def simulate(sol):
            Csh, Rs = sol['Csh'], sol['Rs']
            Rv_sim = Csh*Rvsh + (1-Csh)*Rs
            Rh_sim = Csh/Rhsh + (1-Csh)/Rs
            sim = pd.DataFrame({'Rv_sim':Rv_sim, 'Rh_sim':1/Rh_sim}, index=sol.index)
            return sim
        def error(sol, sim):
            Rv_true, Rh_true = sol['Rv'], sol['Rh']
            Rv_pred, Rh_pred = sim['Rv_sim'], sim['Rh_sim']
            Rv_err = np.abs((Rv_pred - Rv_true) / Rv_true) * 100
            Rh_err = np.abs((Rh_pred - Rh_true) / Rh_true) * 100
            res = pd.DataFrame({'Rv_err':Rv_err, 'Rh_err':Rh_err}, index=sol.index)
            return res
        val = df[['AT10','AT30','AT60','AT90','GR','Csh_lin']]
        sol = inversion()
        sim = simulate(sol)
        err = error(sol, sim)
        self.res_inv = val.join(sol).join(sim).join(err)
        return self.res_inv
    
    def quadratic_inversion(self, df, Rvsh=None, Rhsh=None):
        quad_inv = []
        if Rvsh is None:
            Rvsh = df['Rv'].iloc[np.argmax(df['GR'])]
        if Rhsh is None:
            Rhsh = df['Rh'].iloc[np.argmax(df['GR'])]
        for _, row in df.iterrows():
            Rv, Rh = row['Rv'], row['Rh']
            a = Rh*Rvsh - Rh*Rhsh
            b = Rv**2 + Rvsh*Rhsh - 2*Rh*Rhsh
            c = Rv*Rhsh - Rh*Rhsh
            qsol = np.roots([a,b,c])
            if len(qsol) == 1:
                quad_inv.append({'Csh_q1':qsol[0], 'Csh_q2':np.nan})
            elif len(qsol) == 2:
                quad_inv.append({'Csh_q1':qsol[0], 'Csh_q2':qsol[1]})
            else:
                quad_inv.append({'Csh_q1':np.nan, 'Csh_q2':np.nan})
        self.quad_inv = pd.DataFrame(quad_inv, index=df.index)
        return self.quad_inv
    
    def inversion_uq(self, df):
        '''
        Inversion with uncertainty quantification
        '''
        realizations = []
        sigma_v, sigma_h = np.std(df['Rv']), np.std(df['Rh'])
        for _ in range(self.n_ensemble):
            df_noise = df.copy()
            # Add noise to the data
            e = np.random.normal(0, 1, df.shape[0])
            df_noise['Rv'] = df['Rv'] + e*(self.noise_lvl/100)*sigma_v
            df_noise['Rh'] = df['Rh'] + e*(self.noise_lvl/100)*sigma_h
            # Invert the noisy data
            df_inv = self.resistivity_inversion(df_noise)
            realizations.append(df_inv)
        return realizations
    
    def process_and_plot_uq(self, case, case_uq, figsize=(5,10), lw=0.1, alpha=1):
        csh_ensemble = {}
        for i in range(self.n_ensemble):
            csh_ensemble[i] = case_uq[i]['Csh'].values
        csh_ensemble = np.array(list(csh_ensemble.values()))
        print('Ensemble shape: {}'.format(csh_ensemble.shape))
        plt.figure(figsize=figsize)
        for i in range(self.n_ensemble):
            plt.plot(csh_ensemble[i], case.index, 'k', lw=lw, alpha=alpha)
        plt.gca().invert_yaxis()
        plt.tight_layout(); plt.show()
        return None
    
if __name__ == 'main':
    ari = ARI()
    case1, case2 = ari.load_data()
    ### END ###