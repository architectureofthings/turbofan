"SP Implementation of the TASOPT engine model"
from gpkit import Model, Variable, SignomialsEnabled, units, Vectorize, SignomialEquality
from gpkit.constraints.tight import Tight as TCS
from gpkit.small_scripts import mag
import numpy as np

#import substitution files
from get_737800_subs import get_737800_subs
from get_d82_subs import get_D82_subs
from cfm56_subs import get_cfm56_subs
from get_ge90_subs import get_ge90_subs

#Cp and gamma values estimated from https://www.ohio.edu/mechanical/thermo/property_tables/air/air_Cp_{c}v.html

class Engine(Model):
    """
    Tasopt engine model
    ________
    INPUTS
    res 7 = 0 = Thrust constrained engine, 1 = burner exit temp/turbine entry temp constrained engine
    cooling = True = cooling model, False = no cooling model
    N = number of discrete flight segments
    state = state model discretized into N segments
    eng = 0 = CFM56 vals, 1 = TASOPT 737-800 vals, 2 = GE90 vals, 3 = TASOPT D8.2 vals, 4 = TASOPT 777-300ER vals
    Nfleet - number of discrete missions in a fleet mission optimization problem, default is 0
    """
    Ttmax = True

    def setup(self, res7, cooling, N, state, eng, Nfleet=0, BLI=False):
        """
        setup method for the engine model
        """
        self.setvals(eng, BLI)
        self.compressor = Compressor()
        self.combustor = Combustor()
        self.turbine = Turbine()
        self.fanmap = FanMap()
        self.lpcmap = LPCMap()
        self.hpcmap = HPCMap()
        self.thrust = Thrust()
        self.sizing = Sizing()
        self.constants = EngineConstants(BLI)
        self.state = state

        if Nfleet != 0:
            with Vectorize(Nfleet):
                with Vectorize(N):
                    #-------------------Specified Thrust or Tt4-----------------------
                    self.engineP = self.dynamic(self.state, res7, BLI)
                    OPR = Variable('OPR', '-', 'Overall Pressure Ratio')
                    if res7 == 0:
                        #variables for the thrust constraint
                        Fspec = Variable('F_{spec}', 'N', 'Specified Total Thrust')
                    if res7 == 1:
                        Tt4spec = Variable('T_{t_{4spec}}', 'K', 'Specified Combustor Exit (Station 4) Stagnation Temperature')


        else:
            with Vectorize(N):
                #-------------------Specified Thrust or Tt4-----------------------
                self.engineP = self.dynamic(self.state, res7, BLI)
                OPR = Variable('OPR', '-', 'Overall Pressure Ratio')
                if res7 == 0:
                    #variables for the thrust constraint
                    Fspec = Variable('F_{spec}', 'N', 'Specified Total Thrust')
                if res7 == 1:
                    Tt4spec = Variable('T_{t_{4spec}}', 'K', 'Specified Combustor Exit (Station 4) Stagnation Temperature')


        models = [self.compressor , self. combustor, self. turbine, self. thrust, self.fanmap, self.lpcmap, self.hpcmap, self.sizing, self.state, self.engineP]

        #engine weight
        W_engine = Variable('W_{engine}', 'N', 'Weight of a Single Turbofan Engine')

        #engine fan diameter
        df = Variable('d_{f}', 'm', 'Fan Diameter')
        dlpc = Variable('d_{LPC}', 'm', 'LPC Diameter')
        HTRfSub = Variable('HTR_{f_{SUB}}', '-', '1 - HTRf^2')
        HTRlpcSub = Variable('HTR_{lpc_{SUB}}', '-', '1 - HTRlpc^2')

        #make the constraints
        constraints = []

        with SignomialsEnabled():

            weight = [
                  W_engine/units('kg') >= (self.engineP['m_{total}']/(self.engineP['\\alpha_{+1}']))*((1/(100*units('lb/s')))*9.81*units('m/s^2'))*(1684.5+17.7*(self.engineP['\\pi_{f}']*self.engineP['\\pi_{lc}']*self.engineP['\\pi_{hc}'])/30+1662.2*(self.engineP['\\alpha']/5)**1.2),#*self.engineP['dum2'],
                  ]

            diameter = [
                df == (4 * self.sizing['A_{2}']/(np.pi * HTRfSub))**.5,
                dlpc == (4 * self.sizing['A_{2.5}']/(np.pi * HTRlpcSub))**.5,
                ]

            fmix = [
                #compute f with mixing
                TCS([self.combustor['\\eta_{B}'] * self.engineP['f'] * self.combustor['h_{f}'] >= (1-self.combustor['\\alpha_c'])*self.engineP['h_{t_4}']-(1-self.combustor['\\alpha_c'])*self.engineP['h_{t_3}']+self.combustor['C_{p_{fuel}']*self.engineP['f']*(self.engineP['T_{t_4}']-self.combustor['T_{t_f}'])]),
                #compute Tt41...mixing causes a temperature drop
                #had to include Tt4 here to prevent it from being pushed down to zero
                SignomialEquality(self.engineP['h_{t_{4.1}}']*self.engineP['fp1'], ((1-self.combustor['\\alpha_c']+self.engineP['f'])*self.engineP['h_{t_4}'] + self.combustor['\\alpha_c']*self.engineP['h_{t_3}'])),

                self.engineP['P_{t_4}'] == self.combustor['\\pi_{b}'] * self.engineP['P_{t_3}'],   #B.145
                ]

            fnomix = [
                #only if mixing = false
                #compute f without mixing, overestimation if there is cooling
                TCS([self.combustor['\\eta_{B}'] * self.engineP['f'] * self.combustor['h_{f}'] + self.engineP['h_{t_3}'] >= self.engineP['h_{t_4}']]),

                self.engineP['P_{t_4}'] == self.combustor['\\pi_{b}'] * self.engineP['P_{t_3}'],   #B.145
                ]

            shaftpower = [
                #HPT shafter power balance
                #SIGNOMIAL
                SignomialEquality(self.constants['M_{takeoff}']*self.turbine['\eta_{HPshaft}']*(1+self.engineP['f'])*(self.engineP['h_{t_{4.1}}']-self.engineP['h_{t_{4.5}}']), self.engineP['h_{t_3}'] - self.engineP['h_{t_{2.5}}']),    #B.161

                #LPT shaft power balance
                #SIGNOMIAL
                SignomialEquality(self.constants['M_{takeoff}']*self.turbine['\eta_{LPshaft}']*(1+self.engineP['f'])*
                (self.engineP['h_{t_{4.9}}'] - self.engineP['h_{t_{4.5}}']),-((self.engineP['h_{t_{2.5}}']-self.engineP['h_{t_{1.8}}'])+self.engineP['\\alpha_{+1}']*(self.engineP['h_{t_{2.1}}'] - self.engineP['h_{T_{2}}']))),    #B.165
                ]

            hptexit = [
                #HPT Exit states (station 4.5)
                self.engineP['P_{t_{4.5}}'] == self.engineP['\\pi_{HPT}'] * self.engineP['P_{t_{4.1}}'],
                self.engineP['\\pi_{HPT}'] == (self.engineP['T_{t_{4.5}}']/self.engineP['T_{t_{4.1}}'])**(hptexp1),      #turbine efficiency is 0.9
                ]

            fanmap = [
                self.engineP['\\pi_{f}']*(1.7/self.fanmap['\\pi_{f_D}']) == (1.05*self.engineP['N_{f}']**.0871)**10,
                (self.engineP['\\pi_{f}']*(1.7/self.fanmap['\\pi_{f_D}'])) <= 1.1*(1.06 * (self.engineP['m_{tild_f}'])**0.137)**10,
                (self.engineP['\\pi_{f}']*(1.7/self.fanmap['\\pi_{f_D}'])) >= .9*(1.06 * (self.engineP['m_{tild_f}'])**0.137)**10,

                #define mbar
                self.engineP['m_{f}'] == self.engineP['m_{fan}']*((self.engineP['T_{T_{2}}']/self.constants['T_{ref}'])**.5)/(self.engineP['P_{T_{2}}']/self.constants['P_{ref}']),    #B.280

                self.engineP['\\pi_{f}'] >= 1,

                ]

            lpcmap = [
                self.engineP['\\pi_{lc}']*(26/self.lpcmap['\pi_{lc_D}']) == (1.38 * (self.engineP['N_{1}'])**0.566)**10,
                self.engineP['\\pi_{lc}']*(26/self.lpcmap['\pi_{lc_D}']) <= 1.1*(1.38 * (self.engineP['m_{tild_lc}'])**0.122)**10,
                self.engineP['\\pi_{lc}']*(26/self.lpcmap['\pi_{lc_D}']) >= .9*(1.38 * (self.engineP['m_{tild_lc}'])**0.122)**10,

                self.engineP['\\pi_{lc}'] >= 1,

                #define mbar..technially not needed b/c constrained in res 2 and/or 3
                self.engineP['m_{lc}'] == self.engineP['m_{core}']*((self.engineP['T_{T_{2}}']/self.constants['T_{ref}'])**.5)/(self.engineP['P_{T_{2}}']/self.constants['P_{ref}']),    #B.280
                ]

            hpcmap = [
                self.engineP['\\pi_{hc}']*(26/self.hpcmap['\\pi_{hc_D}']) == (1.38 * (self.engineP['N_{2}'])**0.566)**10,
                self.engineP['\\pi_{hc}']*(26/self.hpcmap['\\pi_{hc_D}']) >= .9*(1.38 * (self.engineP['m_{tild_{hc}}'])**0.122)**10,
                self.engineP['\\pi_{hc}']*(26/self.hpcmap['\\pi_{hc_D}']) <= 1.1*(1.38 * (self.engineP['m_{tild_{hc}}'])**0.122)**10,

                self.engineP['m_{hc}'] == self.engineP['m_{core}']*((self.engineP['T_{t_{2.5}}']/self.constants['T_{ref}'])**.5)/(self.engineP['P_{t_{2.5}}']/self.constants['P_{ref}']),    #B.280

                self.engineP['\\pi_{hc}'] >= 1,
                ]

            opr = [
                OPR == self.engineP['\\pi_{hc}']*self.engineP['\\pi_{lc}']*self.engineP['\\pi_{f}'],
                ]

            thrust = [
                self.engineP['P_{t_8}'] == self.engineP['P_{t_7}'], #B.179
                self.engineP['T_{t_8}'] == self.engineP['T_{t_7}'], #B.180

                self.engineP['P_{t_6}'] == self.engineP['P_{t_5}'], #B.183
                self.engineP['T_{t_6}'] == self.engineP['T_{t_5}'], #B.184

                TCS([self.engineP['F_{6}']/(self.constants['M_{takeoff}']*self.engineP['m_{core}']) + (self.engineP['f']+1)*self.state['V'] <= (self.engineP['fp1'])*self.engineP['u_{6}']]),

                #ISP
                self.engineP['I_{sp}'] == self.engineP['F_{sp}']*self.state['a']*(self.engineP['\\alpha_{+1}'])/(self.engineP['f']*self.constants['g']),  #B.192
                ]

            res1 = [
                #residual 1 Fan/LPC speed
                self.engineP['N_{f}']*self.sizing['G_{f}'] == self.engineP['N_{1}'],
                self.engineP['N_{1}'] <= 1.1,
                self.engineP['N_{2}'] <= 1.1,
                ]

                #note residuals 2 and 3 differ from TASOPT, by replacing mhc with mlc
                #in residual 4 I was able to remove the LPC/HPC mass flow equality
                #in residual 6 which allows for convergence

            res2 = [
                #residual 2 HPT mass flow
                self.sizing['m_{htD}'] == (self.engineP['fp1'])*self.engineP['m_{hc}']*self.constants['M_{takeoff}']*
                (self.engineP['P_{t_{2.5}}']/self.engineP['P_{t_{4.1}}'])*
                (self.engineP['T_{t_{4.1}}']/self.engineP['T_{t_{2.5}}'])**.5,
                ]

            res3 = [
                #residual 3 LPT mass flow
                (self.engineP['fp1'])*self.engineP['m_{lc}']*self.constants['M_{takeoff}']*
                (self.engineP['P_{t_{1.8}}']/self.engineP['P_{t_{4.5}}'])*
                (self.engineP['T_{t_{4.5}}']/self.engineP['T_{t_{1.8}}'])**.5
                == self.sizing['m_{ltD}'],
                ]

            res4 = [
                #residual 4
                (self.engineP['P_{7}']/self.engineP['P_{t_7}']) == (self.engineP['T_{7}']/self.engineP['T_{t_7}'])**(3.5),
                (self.engineP['T_{7}']/self.engineP['T_{t_7}'])**-1 >= 1 + .2 * self.engineP['M_7']**2,
                ]

            res5 = [
                #residual 5 core nozzle mass flow
                (self.engineP['P_{5}']/self.engineP['P_{t_5}']) == (self.engineP['T_{5}']/self.engineP['T_{t_5}'])**(3.583979),
                (self.engineP['T_{5}']/self.engineP['T_{t_5}'])**-1 >= 1 + .2 * self.engineP['M_5']**2,
                ]


            massflux = [
                #compute core mass flux
                self.constants['M_{takeoff}'] * self.engineP['m_{core}'] == self.engineP['\\rho_5'] * self.sizing['A_{5}'] * self.engineP['u_{5}']/(self.engineP['fp1']),

                #compute fan mas flow
                self.engineP['m_{fan}'] == self.engineP['\\rho_7']*self.sizing['A_{7}']*self.engineP['u_{7}'],

                self.engineP['m_{total}'] >= self.engineP['m_{fan}'] + self.engineP['m_{core}'],
                ]

            #component area sizing
            fanarea = [
                #fan area
                self.engineP['P_{2}'] == self.engineP['P_{T_{2}}']*(self.engineP['hold_{2}'])**(-3.512),
                self.engineP['T_{2}'] == self.engineP['T_{T_{2}}'] * self.engineP['hold_{2}']**-1,
                self.sizing['A_{2}'] == self.engineP['m_{fan}']/(self.engineP['\\rho_{2}']*self.engineP['u_{2}']),     #B.198
                ]

            HPCarea = [
                #HPC area
                self.engineP['P_{2.5}'] == self.engineP['P_{t_{2.5}}']*(self.engineP['hold_{2.5}'])**(-3.824857),
                self.engineP['T_{2.5}'] == self.engineP['T_{t_{2.5}}'] * self.engineP['hold_{2.5}']**-1,
                self.sizing['A_{2.5}'] == self.engineP['m_{core}']/(self.engineP['\\rho_{2.5}']*self.engineP['u_{2.5}']),     #B.203
                ]

            if eng == 0:
                """CFM56 vals"""
                onDest = [
                    #estimate relevant on design values
                    self.sizing['m_{htD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1527/101.325),
                    self.sizing['m_{htD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1527/101.325),
                    self.sizing['m_{ltD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1038.8/288)**.5)/(589.2/101.325),
                    self.sizing['m_{ltD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1038.8/288)**.5)/(589.2/101.325),
                    self.lpcmap['m_{lc_D}'] >= .7*self.sizing['m_{coreD}']*((292.57/288)**.5)/(84.25/101.325),
                    self.lpcmap['m_{lc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((292.57/288)**.5)/(84.25/101.325),
                    self.hpcmap['m_{hc_D}'] >= .7*self.sizing['m_{coreD}'] *((362.47/288)**.5)/(163.02/101.325),
                    self.hpcmap['m_{hc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((362.47/288)**.5)/(163.02/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] >= .7 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}'] *((250.0/288)**.5)/(50/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] <= 1.3 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}']* ((250.0/288)**.5)/(50/101.325),
                    ]
            if eng == 1:
                """TASOPT 737-800 vals"""
                onDest = [
                    self.sizing['m_{htD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1498/101.325),
                    self.sizing['m_{htD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}']*((1400.0/288)**.5)/(1498/101.325),
                    self.sizing['m_{ltD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1144.8/288)**.5)/(788.5/101.325),
                    self.sizing['m_{ltD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}']*((1144.8/288)**.5)/(788.5/101.325),
                    self.lpcmap['m_{lc_D}'] >= .7*self.sizing['m_{coreD}']*((294.5/288)**.5)/(84.25/101.325),
                    self.lpcmap['m_{lc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((294.5/288)**.5)/(84.25/101.325),
                    self.hpcmap['m_{hc_D}'] >= .7*self.sizing['m_{coreD}'] *((482.7/288)**.5)/(399.682/101.325),
                    self.hpcmap['m_{hc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((482.7/288)**.5)/(399.682/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] >= .7 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}'] *((250.0/288)**.5)/(50/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] <= 1.3 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}']* ((250.0/288)**.5)/(50/101.325),
                    ]
            if eng == 2:
                """GE90 vals"""
                onDest = [
                    #estimate relevant on design values
                    self.sizing['m_{htD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1527/101.325),
                    self.sizing['m_{htD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1527/101.325),
                    self.sizing['m_{ltD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1038.8/288)**.5)/(589.2/101.325),
                    self.sizing['m_{ltD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1038.8/288)**.5)/(589.2/101.325),
                    self.lpcmap['m_{lc_D}'] >= .7*self.sizing['m_{coreD}']*((292.57/288)**.5)/(84.25/101.325),
                    self.lpcmap['m_{lc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((292.57/288)**.5)/(84.25/101.325),
                    self.hpcmap['m_{hc_D}'] >= .7*self.sizing['m_{coreD}'] *((362.47/288)**.5)/(163.02/101.325),
                    self.hpcmap['m_{hc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((362.47/288)**.5)/(163.02/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] >= .3 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}'] *((250.0/288)**.5)/(50/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] <= 1.7 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}']* ((250.0/288)**.5)/(50/101.325),
                ]

            if eng == 3:
                """TASOPT D8.2 vals"""
                if BLI:
                   onDest = [
                        self.sizing['m_{htD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1433.49/101.325),
                        self.sizing['m_{htD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}']*((1400.0/288)**.5)/(1433.49/101.325),
                        self.sizing['m_{ltD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1121.85/288)**.5)/(706.84/101.325),
                        self.sizing['m_{ltD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}']*((1121.85/288)**.5)/(706.84/101.325),
                        self.lpcmap['m_{lc_D}'] >= .7*self.sizing['m_{coreD}']*((289.77/288)**.5)/(65.79434/101.325),
                        self.lpcmap['m_{lc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((289.77/288)**.5)/(65.79434/101.325),
                        self.hpcmap['m_{hc_D}'] >= .7*self.sizing['m_{coreD}'] *((481.386/288)**.5)/(327.66/101.325),
                        self.hpcmap['m_{hc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((481.386/288)**.5)/(327.66/101.325),
                        self.fanmap['\\bar{m}_{fan_{D}}'] >= .7 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}'] *((250.0/288)**.5)/(41.0/101.325),
                        self.fanmap['\\bar{m}_{fan_{D}}'] <= 1.3 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}']* ((250.0/288)**.5)/(41.0/101.325),
                        ]
                else:
                    onDest = [
                        self.sizing['m_{htD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1400.0/288)**.5)/(1598.32/101.325),
                        self.sizing['m_{htD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}']*((1400.0/288)**.5)/(1598.32/101.325),
                        self.sizing['m_{ltD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1142.6/288)**.5)/(835.585/101.325),
                        self.sizing['m_{ltD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}']*((1142.6/288)**.5)/(835.585/101.325),
                        self.lpcmap['m_{lc_D}'] >= .7*self.sizing['m_{coreD}']*((289.77/288)**.5)/(80.237/101.325),
                        self.lpcmap['m_{lc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((289.77/288)**.5)/(80.237/101.325),
                        self.hpcmap['m_{hc_D}'] >= .7*self.sizing['m_{coreD}'] *((481.386/288)**.5)/(399.58/101.325),
                        self.hpcmap['m_{hc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((481.386/288)**.5)/(399.58/101.325),
                        self.fanmap['\\bar{m}_{fan_{D}}'] >= .7 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}'] *((250.0/288)**.5)/(50/101.325),
                        self.fanmap['\\bar{m}_{fan_{D}}'] <= 1.3 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}']* ((250.0/288)**.5)/(50/101.325),
                        ]

            if eng == 4:
                """TASOPT 777-300ER"""
                onDest = [
                    #estimate relevant on design values
                    self.sizing['m_{htD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1600.0/288)**.5)/(2094.48/101.325),
                    self.sizing['m_{htD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1600.0/288)**.5)/(2094.48/101.325),
                    self.sizing['m_{ltD}'] <= 1.3*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1277.99/288)**.5)/(1022.19/101.325),
                    self.sizing['m_{ltD}'] >= .7*self.engineP['fp1']*self.constants['M_{takeoff}']*self.sizing['m_{coreD}'] *((1277.99/288)**.5)/(1022.19/101.325),
                    self.lpcmap['m_{lc_D}'] >= .7*self.sizing['m_{coreD}']*((289.26/288)**.5)/(79.79/101.325),
                    self.lpcmap['m_{lc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((289.26/288)**.5)/(79.79/101.325),
                    self.hpcmap['m_{hc_D}'] >= .7*self.sizing['m_{coreD}'] *((481.15/288)**.5)/(398.95/101.325),
                    self.hpcmap['m_{hc_D}'] <= 1.3*self.sizing['m_{coreD}'] *((481.15/288)**.5)/(398.95/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] >= .3 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}'] *((250.0/288)**.5)/(50/101.325),
                    self.fanmap['\\bar{m}_{fan_{D}}'] <= 1.7 * self.sizing['\\alpha_{OD}'] * self.sizing['m_{coreD}']* ((250.0/288)**.5)/(50/101.325),
                    ]

        if res7 == 0:
            res7list = [
                #residual 7
                #option #1, constrain the engine's thrust
                self.engineP['F'] == Fspec,
                ]
            if cooling and self.Ttmax:
                Tt41max = Variable('T_{t_{4.1_{max}}}', 'K', 'Max turbine inlet temperature')
                res7list.extend([
                    self.engineP['T_{t_{4.1}}']  <= Tt41max,
                    ])
            elif self.Ttmax:
                Tt4max = Variable('T_{t_{4_{max}}}', 'K', 'Max turbine inlet temperature')
                res7list.extend([
                    self.engineP['T_{t_4}'] <= Tt4max,
                    ])

        if res7 == 1:
            if cooling:
                res7list = [
                    #residual 7
                    #option #2 constrain the burner exit temperature
                    self.engineP['T_{t_{4.1}}'] == Tt4spec,  #B.265
                    ]
            else:
                res7list = [
                    #residual 7
                    #option #2 constrain the burner exit temperature
                    self.engineP['T_{t_4}'] == Tt4spec,  #B.265
                    ]

        if cooling:
            constraints = [weight, diameter, fmix, shaftpower, hptexit, fanmap, lpcmap, hpcmap, opr, thrust, res1, res2, res3, res4, res5, massflux, fanarea, HPCarea, onDest, res7list]
        else:
            constraints = [weight, diameter, fnomix, shaftpower, hptexit, fanmap, lpcmap, hpcmap, opr, thrust, res1, res2, res3, res4, res5, massflux, fanarea, HPCarea, onDest, res7list]

        return models, constraints

    def dynamic(self, state, res7, BLI):
        """
        creates an instance of the engine performance model
        """
        return EnginePerformance(self, state, res7, BLI)

    def setvals(self, eng, BLI):
        global fgamma, lpcgamma, hpcgamma, ccgamma, lptgamma, hptgamma, faneta, fexp1, LPCeta, lpcexp1, \
               HPCeta, hpcexp1, ccexp1, ccexp2, LPTeta, lptexp1, HPTeta, hptexp1, sta8gamma, fanexexp, sta6gamma, turbexexp
        #goption sets the gamma value
        if BLI:
            fan_eta_reduct = 0.96
        else:
            fan_eta_reduct = 1.0

        goption = 1
        if eng == 0:
            """set CFM56 validation exponents"""
            if goption == 1:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.354
                hptgamma = 1.318
            if goption == 0:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.3060
                hptgamma = 1.2987
            #Fan
            faneta = .9005 * fan_eta_reduct
            fexp1 = (fgamma - 1)/(faneta * fgamma)

            #LPC
            LPCeta = .9306
            lpcexp1 = (lpcgamma - 1)/(LPCeta * lpcgamma)

            #HPC
            HPCeta = .9030
            hpcexp1 = (hpcgamma - 1)/(HPCeta * hpcgamma)

            #combustor cooling exponents
            ccexp1 = ccgamma/(1 - ccgamma)
            ccexp2 = -ccgamma/(1 - ccgamma)

            #Turbines
            #LPT
            LPTeta = .8851
            lptexp1 = lptgamma * LPTeta / (lptgamma - 1)

            #HPT
            HPTeta = .8731
            hptexp1 = hptgamma * HPTeta / (hptgamma - 1)

            #Exhaust and Thrust
            #station 8, fan exit
            sta8gamma = 1.4
            fanexexp = (sta8gamma - 1)/ sta8gamma

            #station 6, turbine exit
            sta6gamma = 1.387
            turbexexp = (sta6gamma - 1) / sta6gamma

        if eng == 1:
            """set TASOPT CFM56 validation exponents"""
            if goption == 1:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.354
                hptgamma = 1.318
            if goption == 0:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.3060
                hptgamma = 1.2987

            #Fan
            faneta = .8948 * fan_eta_reduct
            fexp1 = (fgamma - 1)/(faneta * fgamma)

            #LPC
            LPCeta = .88
            lpcexp1 = (lpcgamma - 1)/(LPCeta * lpcgamma)

            #HPC
            HPCeta = .87
            hpcexp1 = (hpcgamma - 1)/(HPCeta * hpcgamma)

            #combustor cooling exponents
            ccexp1 = ccgamma/(1 - ccgamma)
            ccexp2 = -ccgamma/(1 - ccgamma)

            #Turbines
            #LPT
            LPTeta = .889
            lptexp1 = lptgamma * LPTeta / (lptgamma - 1)

            #HPT
            HPTeta = .899
            hptexp1 = hptgamma * HPTeta / (hptgamma - 1)

            #Exhaust and Thrust
            #station 8, fan exit
            sta8gamma = 1.4
            fanexexp = (sta8gamma - 1)/ sta8gamma

            #station 6, turbine exit
            sta6gamma = 1.387
            turbexexp = (sta6gamma - 1) / sta6gamma

        if eng == 3:
            #option used for a D8 engine
            if goption == 1:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.354
                hptgamma = 1.318
            if goption == 0:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.3060
                hptgamma = 1.2987

            #Fan
            faneta = .93 * fan_eta_reduct
            fgamma = 1.4

            fexp1 = (fgamma - 1)/(faneta * fgamma)

            #LPC
            lpcgamma = 1.398
            LPCeta = .92

            lpcexp1 = (lpcgamma - 1)/(LPCeta * lpcgamma)

            #HPC
            HPCeta = .89
            hpcgamma = 1.354

            hpcexp1 = (hpcgamma - 1)/(HPCeta * hpcgamma)

            #combustor cooling exponents
            ccgamma = 1.313    #gamma value of air @ 1400 K

            ccexp1 = ccgamma/(1 - ccgamma)
            ccexp2 = -ccgamma/(1 - ccgamma)

            #Turbines
            #LPT
            lptgamma = 1.354
            LPTeta = .92
            lptexp1 = lptgamma * LPTeta / (lptgamma - 1)

            #HPT
            hptgamma = 1.318
            HPTeta = .91
            hptexp1 = hptgamma * HPTeta / (hptgamma - 1)

            #Exhaust and Thrust
            #station 8, fan exit
            sta8gamma = 1.4
            fanexexp = (sta8gamma - 1)/ sta8gamma

            #station 6, turbine exit
            sta6gamma = 1.387
            turbexexp = (sta6gamma - 1) / sta6gamma

        if eng == 2:
            """set GE90 exponents"""
            if goption == 1:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.354
                hptgamma = 1.318
            if goption == 0:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.3060
                hptgamma = 1.2987

            #Fan
            faneta = .9153 * fan_eta_reduct
            fgamma = 1.4

            fexp1 = (fgamma - 1)/(faneta * fgamma)

            #LPC
            lpcgamma = 1.398
            LPCeta = .9037

            lpcexp1 = (lpcgamma - 1)/(LPCeta * lpcgamma)

            #HPC
            HPCeta = .9247
            hpcgamma = 1.354

            hpcexp1 = (hpcgamma - 1)/(HPCeta * hpcgamma)

            #combustor cooling exponents
            ccgamma = 1.313    #gamma value of air @ 1400 K

            ccexp1 = ccgamma/(1 - ccgamma)
            ccexp2 = -ccgamma/(1 - ccgamma)

            #Turbines
            #LPT
            lptgamma = 1.354
            LPTeta = .9228
            lptexp1 = lptgamma * LPTeta / (lptgamma - 1)

            #HPT
            hptgamma = 1.318
            HPTeta = .9121
            hptexp1 = hptgamma * HPTeta / (hptgamma - 1)

            #Exhaust and Thrust
            #station 8, fan exit
            sta8gamma = 1.4
            fanexexp = (sta8gamma - 1)/ sta8gamma

            #station 6, turbine exit
            sta6gamma = 1.387
            turbexexp = (sta6gamma - 1) / sta6gamma

        if eng == 4:
            """TASOPT 777 vals"""
            if goption == 1:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.354
                hptgamma = 1.318
            if goption == 0:
                fgamma = 1.401
                lpcgamma = 1.398
                hpcgamma = 1.354
                ccgamma = 1.313    #gamma value of air @ 1400 K
                lptgamma = 1.3060
                hptgamma = 1.2987

            #Fan
            faneta = .91 * fan_eta_reduct
            fgamma = 1.4

            fexp1 = (fgamma - 1)/(faneta * fgamma)

            #LPC
            lpcgamma = 1.398
            LPCeta = .90

            lpcexp1 = (lpcgamma - 1)/(LPCeta * lpcgamma)

            #HPC
            HPCeta = .89
            hpcgamma = 1.354

            hpcexp1 = (hpcgamma - 1)/(HPCeta * hpcgamma)

            #combustor cooling exponents
            ccgamma = 1.313    #gamma value of air @ 1400 K

            ccexp1 = ccgamma/(1 - ccgamma)
            ccexp2 = -ccgamma/(1 - ccgamma)

            #Turbines
            #LPT
            lptgamma = 1.354
            LPTeta = .90
            lptexp1 = lptgamma * LPTeta / (lptgamma - 1)

            #HPT
            hptgamma = 1.318
            HPTeta = .90
            hptexp1 = hptgamma * HPTeta / (hptgamma - 1)

            #Exhaust and Thrust
            #station 8, fan exit
            sta8gamma = 1.4
            fanexexp = (sta8gamma - 1)/ sta8gamma

            #station 6, turbine exit
            sta6gamma = 1.387
            turbexexp = (sta6gamma - 1) / sta6gamma

class EnginePerformance(Model):
    """
    Engine performance model
    """
    def setup(self, engine, state, res7, BLI, **kwargs):

        #create the subcomponent performance models
        self.compP = engine.compressor.dynamic(engine.constants, state, BLI)
        self.combP = engine.combustor.dynamic(engine.constants, state)
        self.turbineP = engine.turbine.dynamic(engine.constants)
        self.thrustP = engine.thrust.dynamic(engine.constants, state, BLI)
        self.fanmapP = engine.fanmap.dynamic(engine.constants)
        self.lpcmapP = engine.lpcmap.dynamic(engine.constants)
        self.hpcmapP = engine.hpcmap.dynamic(engine.constants)
        self.sizingP = engine.sizing.dynamic(engine.constants, engine.compressor, engine.fanmap, engine.lpcmap, engine.hpcmap, state, res7)

        models = [self.compP, self.combP, self.turbineP, self.thrustP, self.fanmapP, self.lpcmapP, self.hpcmapP, self.sizingP]

        return models

class EngineConstants(Model):
    """
    Class of constants used in the engine model
    """
    def setup(self, BLI):
        #-----------------------air properties------------------
        #ambient
        R = Variable('R', 287, 'J/kg/K', 'R')

        #gravity
        g = Variable('g', 9.81, 'm/(s^2)', 'Gravitational Acceleration')

        #-------------------------reference temp and pressure--------------------
        Tref = Variable('T_{ref}', 'K', 'Reference Stagnation Temperature')
        Pref = Variable('P_{ref}', 'kPa', 'Reference Stagnation Pressure')

        #---------------------------efficiencies & takeoffs-----------------------
        Mtakeoff = Variable('M_{takeoff}', '-', '1 Minus Percent mass flow loss for de-ice, pressurization, etc.')

        #----------------BLI pressure loss factor-------------------
        if BLI:
            fBLIP = Variable('f_{BLI_{P}}', '-', 'BLI Stagnation Pressure Loss Ratio')
            fBLIV = Variable('f_{BLI_{V}}', '-', 'BLI Velocity Loss Ratio')

class Compressor(Model):
    """"
    Compressor model
    """
    def setup(self):
        #define new variables
        #fan, LPC, HPC
        Cp1 = Variable('C_{p_{1}', 1008, 'J/kg/K', "Cp Value for Air at 350K")#gamma = 1.398
        Cp2 = Variable('C_{p_{2}', 1099, 'J/kg/K', "Cp Value for Air at 800K") #gamma = 1.354

        #-------------------------diffuser pressure ratios--------------------------
        pid = Variable('\pi_{d}', '-', 'Diffuser Pressure Ratio')
        pifn = Variable('\\pi_{fn}', '-', 'Fan Duct Pressure Loss Ratio')

        gammaAir = Variable('\\gamma_{air}', 1.4, '-', 'Specific Heat Ratio for Ambient Air')
        Cpair = Variable('C_{p_{air}', 1003, 'J/kg/K', "Cp Value for Air at 250K")

    def dynamic(self, engine, state, BLI):
        """
        creates an instance of the compressor performance model
        """
        return CompressorPerformance(self, engine, state, BLI)

class CompressorPerformance(Model):
    """
    combustor perfomrance constraints
    """
    def setup(self, comp, engine, state, BLI):
        self.comp = comp
        self.engine = engine

        #define new variables
        #--------------------------free stream stagnation states--------------------------
        Pt0 = Variable('P_{t_0}', 'kPa', 'Free Stream Stagnation Pressure')
        Tt0 = Variable('T_{t_0}', 'K', 'Free Stream Stagnation Temperature')
        ht0 = Variable('h_{t_0}', 'J/kg', 'Free Stream Stagnation Enthalpy')

        #--------------------------diffuser exit stagnation states------------------------
        Pt18 = Variable('P_{t_{1.8}}', 'kPa', 'Stagnation Pressure at the Diffuser Exit (1.8)')
        Tt18 = Variable('T_{t_{1.8}}', 'K', 'Stagnation Temperature at the Diffuser Exit (1.8)')
        ht18 = Variable('h_{t_{1.8}}', 'J/kg', 'Stagnation Enthalpy at the Diffuser Exit (1.8)')

        #--------------------------fan inlet (station 2) stagnation states---------------------------
        Pt2 = Variable('P_{T_{2}}', 'kPa', 'Stagnation Pressure at the Fan Inlet (2)')
        Tt2 = Variable('T_{T_{2}}', 'K', 'Stagnation Temperature at the Fan Inlet (2)')
        ht2 = Variable('h_{T_{2}}', 'J/kg', 'Stagnation Enthalpy at the Fan Inlet (2)')

        #--------------------------fan exit (station 2.1) stagnation states---------------------
        Pt21 = Variable('P_{t_{2.1}}', 'kPa', 'Stagnation Pressure at the Fan Exit (2.1)')
        Tt21 = Variable('T_{t_{2.1}}', 'K', 'Stagnation Temperature at the Fan Exit (2.1)')
        ht21 = Variable('h_{t_{2.1}}', 'J/kg', 'Stagnation Enthalpy at the Fan Exit (2.1)')

        #-------------------------LPC exit (station 2.5) stagnation states-------------------
        Pt25 = Variable('P_{t_{2.5}}', 'kPa', 'Stagnation Pressure at the LPC Exit (2.5)')
        Tt25 = Variable('T_{t_{2.5}}', 'K', 'Stagnation Temperature at the LPC Exit (2.5)')
        ht25 = Variable('h_{t_{2.5}}', 'J/kg', 'Stagnation Enthalpy at the LPC Exit (2.5)')

        #--------------------------HPC exit stagnation states (station 3)---------------------
        Pt3 = Variable('P_{t_3}', 'kPa', 'Stagnation Pressure at the HPC Exit (3)')
        Tt3 = Variable('T_{t_3}', 'K', 'Stagnation Temperature at the HPC Exit (3)')
        ht3 = Variable('h_{t_3}', 'J/kg', 'Stagnation Enthalpy at the HPC Exit (3)')

        #---------------------------fan nozzle exit (station 7) stagnation states---------------
        Pt7 = Variable('P_{t_7}', 'kPa', 'Stagnation Pressure at the Fan Nozzle Exit (7)')
        Tt7 = Variable('T_{t_7}', 'K', 'Stagnation Temperature at the Fan Nozzle Exit (7)')
        ht7 = Variable('h_{t_7}', 'J/kg', 'Stagnation Enthalpy at the Fan Nozzle Exit (7)')

        #------------------------turbo machinery pressure ratios--------------
        pif = Variable('\\pi_{f}', '-', 'Fan Pressure Ratio')
        pilc = Variable('\\pi_{lc}', '-', 'LPC Pressure Ratio')
        pihc = Variable('\\pi_{hc}', '-', 'HPC Pressure Ratio')

        hold25 = Variable('hold_{2.5}', '-', '1+(gamma-1)/2 * M_2.5**2')
        hold2 = Variable('hold_{2}', '-', '1+(gamma-1)/2 * M_2**2')
        c1 = Variable('c1', '-', 'Constant in Stagnation Eqn')

        diffuser = [
            #free stream stagnation values
             #https://www.grc.nasa.gov/www/k-12/airplane/isentrop.html
            Tt0 == state["T_{atm}"] / (c1) ** (-1),             #https://www.grc.nasa.gov/www/k-12/airplane/isentrop.html
            ht0 == self.comp['C_{p_{air}'] * Tt0,

            #diffuser exit stagnation values (station 1.8)
            Pt18 == self.comp['\pi_{d}'] * Pt0,  #B.113
            Tt18 == Tt0,        #B.114
            ht18 == ht0,        #B.115
            ]

        if BLI:
            diffuser.extend([
                Pt0 == self.engine['f_{BLI_{P}}']*state["P_{atm}"] / (c1 ** -3.5),
                ])

        if not BLI:
            diffuser.extend([
                Pt0 == state["P_{atm}"] / (c1 ** -3.5),
                ])

        fan = [
            #fan inlet constraints (station 2)
            Tt2 == Tt18,    #B.120
            ht2 == ht18,    #B.121
            Pt2 == Pt18,

            #fan exit constraints (station 2.1)
            Pt21 == pif * Pt2,  #16.50
            Tt21 == Tt2 * pif ** (fexp1),   #16.50
            ht21 == self.comp['C_{p_{air}'] * Tt21,   #16.50

            #fan nozzle exit (station 7)
            Pt7 == self.comp['\\pi_{fn}'] * Pt21,     #B.125
            Tt7 == Tt21,    #B.126
            ht7 == ht21,    #B.127
            ]

        lpc = [
            #LPC exit (station 2.5)
            Pt25 == pilc * pif * Pt2,
            Tt25 == Tt2 * (pif*pilc) ** (lpcexp1),
            ht25 == Tt25 * self.comp['C_{p_{1}'],
            ]

        hpc = [
            Pt3 == pihc * Pt25,
            Tt3 == Tt25 * pihc ** (hpcexp1),
            ht3 == self.comp['C_{p_{2}'] * Tt3
            ]

        return diffuser, fan, lpc, hpc

class Combustor(Model):
    """"
    Combustor model
    """
    def setup(self):
        #define new variables
        Cpc = Variable('C_{p_{c}}', 1216, 'J/kg/K', "Cp Value for Fuel/Air Mix in Combustor") #1400K, gamma equals 1.312
        Cpfuel = Variable('C_{p_{fuel}', 2010, 'J/kg/K', 'Specific Heat Capacity of Kerosene (~Jet Fuel)')
        hf = Variable('h_{f}', 43.003, 'MJ/kg', 'Heat of Combustion of Jet Fuel')     #http://hypeRbook.com/facts/2003/EvelynGofman.shtml...prob need a better source

        #-------------------------diffuser pressure ratios--------------------------
        pib = Variable('\\pi_{b}', '-', 'Burner Pressure Ratio')

        #---------------------------efficiencies & takeoffs-----------------------
        etaB = Variable('\\eta_{B}', '-', 'Burner Efficiency')

        #------------------------Variables for cooling flow model---------------------------
        #cooling flow bypass ratio
        ac = Variable('\\alpha_c', '-', 'Total Cooling Flow Bypass Ratio')
        #variables for cooling flow velocity
        ruc = Variable('r_{uc}', '-', 'User Specified Cooling Flow Velocity Ratio')

        hold4a = Variable('hold_{4a}', '-', '1+(gamma-1)/2 * M_4a**2')

        Ttf = Variable('T_{t_f}', 'K', 'Incoming Fuel Total Temperature')

    def dynamic(self, engine, state):
        """
        creates an instance of the fan map performance model
        """
        return CombustorPerformance(self, engine, state)

class CombustorPerformance(Model):
    """
    combustor perfomrance constraints
    """
    def setup(self, combustor, engine, state, mixing = True):
        self.combustor = combustor
        self.engine = engine

        #define new variables
        #--------------------------combustor exit (station 4) stagnation states------------------
        Pt4 = Variable('P_{t_4}', 'kPa', 'Stagnation Pressure at the Combustor Exit (4)')
        ht4 = Variable('h_{t_4}', 'J/kg', 'Stagnation Enthalpy at the Combustor Exit (4)')
        Tt4 = Variable('T_{t_4}', 'K', 'Combustor Exit (Station 4) Stagnation Temperature')

        #--------------------High Pressure Turbine inlet state variables (station 4.1)-------------------------
        Pt41 = Variable('P_{t_{4.1}}', 'kPa', 'Stagnation Pressure at the Turbine Inlet (4.1)')
        Tt41 = Variable('T_{t_{4.1}}', 'K', 'Stagnation Temperature at the Turbine Inlet (4.1)')
        ht41 = Variable('h_{t_{4.1}}', 'J/kg', 'Stagnation Enthalpy at the Turbine Inlet (4.1)')
        u41 = Variable('u_{4.1}', 'm/s', 'Flow Velocity at Station 4.1')
        T41 = Variable('T_{4.1}', 'K', 'Static Temperature at the Turbine Inlet (4.1)')

        #------------------------Variables for cooling flow model---------------------------
        #define the f plus one variable, limits the number of signomials
        #variables for station 4a
        u4a = Variable('u_{4a}', 'm/s', 'Flow Velocity at Station 4a')
        M4a = Variable('M_{4a}', '-', 'User Specified Station 4a Mach #')
        P4a = Variable('P_{4a}', 'kPa', 'Static Pressure at Station 4a (4a)')
        uc = Variable('u_c', 'm/s', 'Cooling Airflow Speed at Station 4a')

        #---------------------------fuel flow fraction f--------------------------------
        f = Variable('f', '-', 'Fuel Air Mass Flow Fraction')
        fp1 = Variable('fp1', '-', 'f + 1')

        #make the constraints
        constraints = []

        with SignomialsEnabled():
            #combustor constraints
            constraints.extend([
                #flow through combustor
                ht4 == self.combustor['C_{p_{c}}'] * Tt4,

                #compute the station 4.1 enthalpy
                ht41 == self.combustor['C_{p_{c}}'] * Tt41,

                #making f+1 GP compatible --> needed for convergence
                SignomialEquality(fp1,f+1),

                #investigate doing this with a substitution
                M4a == .1025,
                ])

            #mixing constraints
            if mixing:
                constraints.extend([
                    fp1*u41 == (u4a*(fp1)*self.combustor['\\alpha_c']*uc)**.5,
                    #this is a stagnation relation...need to fix it to not be signomial
                    SignomialEquality(T41, Tt41-.5*(u41**2)/self.combustor['C_{p_{c}}']),

                    #here we assume no pressure loss in mixing so P41=P4a
                    Pt41 == P4a*(Tt41/T41)**(ccexp1),

                    #compute station 4a quantities, assumes a gamma value of 1.313 (air @ 1400K)
                    u4a == M4a*((1.313*self.engine['R']*Tt4)**.5)/self.combustor['hold_{4a}'],
                    uc == self.combustor['r_{uc}']*u4a,
                    P4a == Pt4*self.combustor['hold_{4a}']**(ccexp2),
                    ])
            #combustor constraints with no mixing
            else:
                constraints.extend([
                    Pt41 == Pt4,
                    Tt41 == Tt4,
                    ])

        return constraints

class Turbine(Model):
    """"
    Turbine model
    """
    def setup(self):
        #define new variables
        #turbines
        Cpt1 = Variable('C_{p_{t1}}', 1280, 'J/kg/K', "Cp Value for Combustion Products in HP Turbine") #1300K gamma = 1.318
        Cpt2 = Variable('C_{p_{t2}}', 1184, 'J/kg/K', "Cp Value for Combustion Products in LP Turbine") #800K gamma = 1.354

        #-------------------------diffuser pressure ratios--------------------------
        pitn = Variable('\\pi_{tn}', '-', 'Turbine Nozzle Pressure Ratio')

        #---------------------------efficiencies & takeoffs-----------------------
        etaHPshaft = Variable('\eta_{HPshaft}', '-', 'Power Transmission Efficiency of High Pressure Shaft, Smears in Losses for Electrical Power')
        etaLPshaft = Variable('\eta_{LPshaft}', '-', 'Power Transmission Efficiency of Low Pressure Shaft, Smeras in Losses for Electrical Power')

    def dynamic(self, engine):
        """
        creates an instance of the fan map performance model
        """
        return TurbinePerformance(self, engine)

class TurbinePerformance(Model):
    """
    combustor perfomrance constraints
    """
    def setup(self, turbine, engine):
        self.turbine = turbine
        self.engine = engine

        #define new variables
        #------------------LPT inlet stagnation states (station 4.5)------------------
        ht45 = Variable('h_{t_{4.5}}', 'J/kg', 'Stagnation Enthalpy at the HPT Exit (4.5)')
        Pt45 = Variable('P_{t_{4.5}}', 'kPa', 'Stagnation Pressure at the HPT Exit (4.5)')
        Tt45 = Variable('T_{t_{4.5}}', 'K', 'Stagnation Temperature at the HPT Exit (4.5)')

        #-------------------HPT exit (station 4.5) stagnation states--------------------
        Pt49 = Variable('P_{t_{4.9}}', 'kPa', 'Stagnation Pressure at the HPTExit (49)')
        Tt49 = Variable('T_{t_{4.9}}', 'K', 'Stagnation Temperature at the HPT Exit (49)')
        ht49 = Variable('h_{t_{4.9}}', 'J/kg', 'Stagnation Enthalpy at the HPT Exit (49)')

        #------------------------turbo machinery pressure ratios--------------
        pihpt = Variable('\\pi_{HPT}', '-', 'HPT Pressure Ratio')
        pilpt = Variable('\\pi_{LPT}', '-', 'LPT Pressure Ratio')

        #------------------turbine nozzle exit stagnation states (station 5)------------
        Pt5 = Variable('P_{t_5}', 'kPa', 'Stagnation Pressure at the Turbine Nozzle Exit (5)')
        Tt5 = Variable('T_{t_5}', 'K', 'Stagnation Temperature at the Turbine Nozzle Exit (5)')
        ht5 = Variable('h_{t_5}', 'J/kg', 'Stagnation Enthalpy at the Turbine Nozzle Exit (5)')

        #make the constraints
        constraints = []

        #turbine constraints
        constraints.extend([
            #HPT Exit states (station 4.5)
            ht45 == self.turbine['C_{p_{t1}}'] * Tt45,

            #LPT Exit States
            Pt49 == pilpt * Pt45,
            pilpt == (Tt49/Tt45)**(lptexp1),    #turbine efficiency is 0.9
            ht49 == self.turbine['C_{p_{t2}}'] * Tt49,

            #turbine nozzle exit states
            Pt5 == self.turbine['\\pi_{tn}'] * Pt49, #B.167
            Tt5 == Tt49,    #B.168
            ht5 == ht49     #B.169
            ])

        return constraints

class FanMap(Model):
    """"
    Fan map model
    """
    def setup(self):
        #define new variables
        #------------------Fan map variables----------------
        mFanBarD = Variable('\\bar{m}_{fan_{D}}', 'kg/s', 'Fan On-Design Corrected Mass Flow')
        piFanD = Variable('\\pi_{f_D}', '-', 'On-Design Pressure Ratio')

    def dynamic(self, engine):
        """
        creates an instance of the fan map performance model
        """
        return FanMapPerformance(self, engine)

class FanMapPerformance(Model):
    """
    Fan map perfomrance constraints
    """
    def setup(self, fanmap, engine):
        self.fanmap = fanmap
        self.engine = engine

        #define new variables
        #-----------------------Fan Map Variables--------------------
        #Mass Flow Variables
        mf = Variable('m_{f}', 'kg/s', 'Fan Corrected Mass Flow')
        mtildf = Variable('m_{tild_f}', '-', 'Fan Normalized Mass Flow')

        #----------------------Compressor Speeds--------------------
        #Speed Variables...by setting the design speed to be 1 since only ratios are
        #imporant I was able to drop out all the other speeds
        Nf = Variable('N_{f}', '-', 'Fan Speed')

        #make the constraints
        constraints = []

        #fan map
        constraints.extend([
            #define mtild
            mtildf == mf/self.fanmap['\\bar{m}_{fan_{D}}'],   #B.282
            ])

        return constraints

class LPCMap(Model):
    """"
    LPC map model
    """
    def setup(self):
        #define new variables
        #-----------------LPC map variables-------------------
        mlcD = Variable('m_{lc_D}', 'kg/s', 'On Design LPC Corrected Mass Flow')
        pilcD = Variable('\pi_{lc_D}', '-', 'LPC On-Design Pressure Ratio')

    def dynamic(self, engine):
        """
        creates an instance of the HPC map performance model
        """
        return LPCMapPerformance(self, engine)

class LPCMapPerformance(Model):
    """
    LPC map perfomrance constraints
    """
    def setup(self, lpcmap, engine):
        self.lpcmap = lpcmap
        self.engine = engine

        #define new variables
        #-------------------------LPC Map Variables-------------------------
        #Mass Flow Variables
        mlc = Variable('m_{lc}', 'kg/s', 'LPC Corrected Mass Flow')
        mtildlc = Variable('m_{tild_lc}', '-', 'LPC Normalized Mass Flow')

        #----------------------Compressor Speeds--------------------
        #Speed Variables...by setting the design speed to be 1 since only ratios are
        #imporant I was able to drop out all the other speeds
        N1 = Variable('N_{1}', '-', 'LPC Speed')

        #make the constraints
        constraints = []

        #LPC map
        constraints.extend([
            #define mtild
            mtildlc == mlc/self.lpcmap['m_{lc_D}'],   #B.282
        ])

        return constraints

class HPCMap(Model):
    """"
    HPC map model
    """
    def setup(self):
        #define new variables
        #-----------------HPC map variables-----------
        mhcD = Variable('m_{hc_D}', 'kg/s', 'On Design HPC Corrected Mass Flow')
        pihcD = Variable('\\pi_{hc_D}', '-', 'HPC On-Design Pressure Ratio')
        mhcD = Variable('m_{hc_D}', 'kg/s', 'On Design HPC Corrected Mass Flow')

    def dynamic(self, engine):
        """
        creates an instance of the HPC map performance model
        """
        return HPCMapPerformance(self, engine)

class HPCMapPerformance(Model):
    """
    HPC map perfomrance constraints
    """
    def setup(self, hpcmap, engine):
        self.hpcmap = hpcmap
        self.engine = engine

        #define new variables
        #--------------------------HPC Map Variables------------------
        #Mass Flow Variables
        mhc = Variable('m_{hc}', 'kg/s', 'HPC Corrected Mass Flow')
        mtildhc = Variable('m_{tild_{hc}}', '-', 'HPC Normalized Mass Flow')

        #----------------------Compressor Speeds--------------------
        #Speed Variables...by setting the design speed to be 1 since only ratios are
        #imporant I was able to drop out all the other speeds
        N2 = Variable('N_{2}', '-', 'HPC Speed')

        #make the constraints
        constraints = []

        #HPC map
        constraints.extend([
            #define mtild
            mtildhc == mhc/self.hpcmap['m_{hc_D}'],   #B.282
            ])

        return constraints

class Thrust(Model):
    """"
    thrust sizing model
    """
    def setup(self):
        #define new variables
        #fan and exhaust
        Cptex =Variable('C_{p_{tex}', 1029, 'J/kg/K', "Cp Value for Combustion Products at Core Exhaust") #500K, gamma = 1.387
        Cpfanex = Variable('C_{p_{fex}', 1005, 'J/kg/K', "Cp Value for Air at 300K") #gamma =1.4        #heat of combustion of jet fuel

        #max by pass ratio
        alpha_max = Variable('\\alpha_{max}', '-', 'By Pass Ratio')

    def dynamic(self, engine, state, BLI):
        """
        creates an instance of the thrust performance model
        """
        return ThrustPerformance(self, engine, state, BLI)

class ThrustPerformance(Model):
    """
    thrust performacne model
    """
    def setup(self, thrust, engine, state, BLI):
        self.thrust = thrust
        self.engine = engine

        #define new variables
        #------------------fan exhaust (station 8) statge variables------------
        P8 = Variable('P_{8}', 'kPa', 'Fan Exhaust Static Pressure')
        Pt8 = Variable('P_{t_8}', 'kPa', 'Fan Exhaust Stagnation Pressure')
        ht8 = Variable('h_{t_8}', 'J/kg', 'Fan Exhaust Stagnation Enthalpy')
        h8 = Variable('h_{8}', 'J/kg', 'Fan Exhasut Static Enthalpy')
        Tt8 = Variable('T_{t_8}', 'K', 'Fan Exhaust Stagnation Temperature (8)')
        T8 = Variable('T_{8}', 'K', 'Fan Exhaust Sttic Temperature (8)')

        #-----------------core exhaust (station 6) state variables-------------
        P6 = Variable('P_{6}', 'kPa', 'Core Exhaust Static Pressure')
        Pt6 = Variable('P_{t_6}', 'kPa', 'Core Exhaust Stagnation Pressure')
        Tt6 = Variable('T_{t_6}', 'K', 'Core Exhaust Stagnation Temperature (6)')
        T6 = Variable('T_{6}', 'K', 'Core Exhaust Static Temperature (6)')
        ht6 = Variable('h_{t_6}', 'J/kg', 'Core Exhaust Stagnation Enthalpy')
        h6 = Variable('h_6', 'J/kg', 'Core Exhasut Static Enthalpy')

        #thrust variables
        F8 = Variable('F_{8}', 'N', 'Fan Thrust')
        F6 = Variable('F_{6}', 'N', 'Core Thrust')
        F = Variable('F', 'N', 'Total Thrust')
        Fsp = Variable('F_{sp}', '-', 'Specific Net Thrust')
        Isp = Variable('I_{sp}', 's', 'Specific Impulse')
        TSFC = Variable('TSFC', '1/hr', 'Thrust Specific Fuel Consumption')

        #exhaust speeds
        u6 = Variable('u_{6}', 'm/s', 'Core Exhaust Velocity')
        u8 = Variable('u_{8}', 'm/s', 'Fan Exhaust Velocity')

        #mass flows
        mCore = Variable('m_{core}', 'kg/s', 'Core Mass Flow')
        mFan = Variable('m_{fan}', 'kg/s', 'Fan Mass Flow')

        #------------------By-Pass Ratio (BPR)----------------------------
        alpha = Variable('\\alpha', '-', 'By Pass Ratio')
        alphap1 = Variable('\\alpha_{+1}', '-', '1 plus BPR')

        hold = Variable('hold', '-', 'unecessary hold var')

        #constraints
        constraints = []

        with SignomialsEnabled():
            #exhaust and thrust constraints
            constraints.extend([
                P8 == state["P_{atm}"],
                h8 == self.thrust['C_{p_{fex}'] * T8,
                TCS([u8**2 + 2*h8 <= 2*ht8]),
                (P8/Pt8)**(fanexexp) == T8/Tt8,
                ht8 == self.thrust['C_{p_{fex}'] * Tt8,

                #core exhaust
                P6 == state["P_{atm}"],   #B.4.11 intro
                (P6/Pt6)**(turbexexp) == T6/Tt6,
                TCS([u6**2 + 2*h6 <= 2*ht6]),
                h6 == self.thrust['C_{p_{tex}'] * T6,
                ht6 == self.thrust['C_{p_{tex}'] * Tt6,

                #constrain the new BPR
                alpha == mFan / mCore,
                hold == alphap1,
                SignomialEquality(hold, alpha + 1),
                alpha <= self.thrust['\\alpha_{max}'],

                #SIGNOMIAL
                TCS([F <= F6 + F8]),

                Fsp == F/((alphap1)*mCore*state['a']),   #B.191

                #TSFC
                TSFC == 1/Isp,
                ])

        if BLI:
            constraints.extend([
                #overall thrust values
                TCS([F8/(alpha * mCore) + state['V']*engine['f_{BLI_{V}}'] <= u8]),  #B.188
                ])

        else:
            constraints.extend([
                #overall thrust values
                TCS([F8/(alpha * mCore) + state['V'] <= u8]),  #B.188
                ])

        return constraints

class Sizing(Model):
    """"
    engine sizing model
    """
    def setup(self):
        #define new variables
        #gear ratio, set to 1 if no gearing present
        Gf = Variable('G_{f}', '-', 'Gear Ratio Between Fan and LPC')

        mhtD = Variable('m_{htD}', 'kg/s', 'Design HPT Corrected Mass Flow (see B.225)')
        mltD = Variable('m_{ltD}', 'kg/s', 'Design LPT Corrected Mass Flow (see B.226)')

        #on design by pass ratio
        alpha_max = Variable('\\alpha_{OD}', '-', 'By Pass Ratio')

        #-------------------------Areas------------------------
        A2 = Variable('A_{2}', 'm^2', 'Fan Area')
        A25 = Variable('A_{2.5}', 'm^2', 'HPC Area')
        A5 = Variable('A_{5}', 'm^2', 'Core Exhaust Nozzle Area')
        A7 = Variable('A_{7}', 'm^2', 'Fan Exhaust Nozzle Area')

        mCoreD = Variable('m_{coreD}', 'kg/s', 'Estimated on Design Mass Flow')

        #constraints
        constraints = []

        constraints.extend([
            #-------------------------Areas------------------------
            A5 + A7 <= A2,
            ])

        return constraints

    def dynamic(self, engine, compressor, fanmap, lpcmap, hpcmap, state, res7):
        """
        creates an instance of the engine sizing performance model
        """
        return SizingPerformance(self, engine, compressor, fanmap, lpcmap, hpcmap, state, res7)

class SizingPerformance(Model):
    """
    engine sizing perofrmance model
    """
    def setup(self, sizing, engine, compressor, fanmap, lpcmap, hpcmap, state, res7, cooling = True):
        self.sizing = sizing
        self.engine = engine
        self.compressor = compressor
        self.fanmap = fanmap
        self.lpcmap = lpcmap
        self.hpcmap = hpcmap

        #new variables
        #exhaust mach numbers
        a5 = Variable('a_{5}', 'm/s', 'Speed of Sound at Station 5')
        a7 = Variable('a_{7}', 'm/s', 'Speed of Sound at Station 7')

        #mass flows
        mtot = Variable('m_{total}', 'kg/s', 'Total Engine Mass Flux')

        #-------------------fan face variables---------------------
        rho2 = Variable('\\rho_{2}', 'kg/m^3', 'Air Static Density at Fan Face')
        T2 = Variable('T_{2}', 'K', 'Air Static Temperature at Fan Face')
        P2 = Variable('P_{2}', 'kPa', 'Air Static Pressure at Fan Face')
        u2 = Variable('u_{2}', 'm/s', 'Air Speed at Fan Face')
        h2 = Variable('h_{2}', 'J/kg', 'Static Enthalpy at the Fan Inlet (2)')
        M2 = Variable('M_2', '-', 'Fan Face/LPC Face Axial Mach Number')

        #------------------HPC face variables---------------------
        rho25 = Variable('\\rho_{2.5}', 'kg/m^3', 'Static Air Density at HPC Face')
        T25 = Variable('T_{2.5}', 'K', 'Static Air Temperature at HPC Face')
        P25 = Variable('P_{2.5}', 'kPa', 'Static Air Pressure at HPC Face')
        u25 = Variable('u_{2.5}', 'm/s', 'Air Speed at HPC Face')
        h25 = Variable('h_{2.5}', 'J/kg', 'Static Enthalpy at the LPC Exit (2.5)')
        M25 = Variable('M_{2.5}', '-', 'HPC Face Axial Mach Number')

        #fan exhuast states
        P7 = Variable('P_{7}', 'kPa', 'Fan Exhaust Static Pressure (7)')
        T7 = Variable('T_{7}', 'K', 'Static Temperature at the Fan Nozzle Exit (7)')
        u7 = Variable('u_{7}', 'm/s', 'Station 7 Exhaust Velocity')
        M7 = Variable('M_7', '-', 'Station 7 Mach Number')
        rho7 = Variable('\\rho_7', 'kg/m^3', 'Air Static Density at Fam Exhaust Exit (7)')

        #core exhaust states
        P5 = Variable('P_{5}', 'kPa', 'Core Exhaust Static Pressure (5)')
        T5 = Variable('T_{5}', 'K', 'Static Temperature at the Turbine Nozzle Exit (5)')
        M5 = Variable('M_5', '-', 'Station 5 Mach Number')
        u5 = Variable('u_{5}', 'm/s', 'Station 5 Exhaust Velocity')
        rho5 = Variable('\\rho_5', 'kg/m^3', 'Air Static Density at Core Exhaust Exit (5)')

        #dummy vairables for pint purposes
        dum = Variable("dum", 781, 'J/kg/K')
        dum2 = Variable('dum2', 1, 'm/s')

        #constraints
        constraints = []

        #sizing constraints that hold the engine together
        constraints.extend([
            #residual 4
            P7 >= state["P_{atm}"],
            M7 <= 1,
            a7 == (1.4*self.engine['R']*T7)**.5,
            a7*M7 == u7,
            rho7 == P7/(self.engine['R']*T7),

            #residual 5 core nozzle mass flow
            P5 >= state["P_{atm}"],
            M5 <= 1,
            a5 == (1.387*self.engine['R']*T5)**.5,
            a5*M5 == u5,
            rho5 == P5/(self.engine['R']*T5),

            #component area sizing
            #fan area
            h2 == self.compressor['C_{p_{1}'] * T2,
            rho2 == P2/(self.engine['R'] * T2),  #B.196
            u2 == M2*(self.compressor['C_{p_{1}']*self.engine['R']*T2/(dum))**.5,  #B.197

            #HPC area
            h25 == self.compressor['C_{p_{2}'] * T25,
            rho25 == P25/(self.engine['R']*T25),
            u25 == M25*(self.compressor['C_{p_{2}']*self.engine['R']*T25/(dum))**.5,   #B.202
        ])

        return constraints

class TestState(Model):
    """
    state class only to be used for testing purposes
    """
    def setup(self):
        #define variables
        p_atm = Variable("P_{atm}", "kPa", "air pressure")
        TH = 5.257386998354459
        T_atm = Variable("T_{atm}", "K", "air temperature")

        V = Variable('V', 'kts', 'Aircraft Flight Speed')
        a = Variable('a', 'm/s', 'Speed of Sound')
        R = Variable('R', 287, 'J/kg/K', 'Air Specific Heat')
        gamma = Variable('\\gamma', 1.4, '-', 'Air Specific Heat Ratio')
        M = Variable('M', '-', 'Mach Number')

        #make constraints
        constraints = []

        constraints.extend([
            V == M * a,
            a  == (gamma * R * T_atm)**.5,
            ])

        return constraints

class TestMissionCFM(Model):
    """
    place holder of a mission calss
    """
    def setup(self, engine):
        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .8

        climb = [
            engine['F_{spec}'][0] == 5496.4 * 4.4 * units('N'),
            engine['F_{spec}'][1] == 5961.9 *4.4 * units('N'),

            engine.state["T_{atm}"] == 218*units('K'),


            engine.state['P_{atm}'][0] == 23.84*units('kPa'),    #36K feet
            engine.state['M'][0] == M0,
            engine.engineP['M_2'][0] == M2,
            engine.engineP['M_{2.5}'][0] == M25,
            engine.engineP['hold_{2}'] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'] == 1+.5*(.401)*M0**2,
            ]

        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .8

        cruise = [
            engine.state['P_{atm}'][1] == 23.84*units('kPa'),    #36K feet
            engine.state['M'][1] == M0,
            engine.engineP['M_2'][1] == M2,
            engine.engineP['M_{2.5}'][1] == M25,

            engine['W_{engine}'] <= 5216*units('lbf'),
            ]

        return climb, cruise

class TestMissionTASOPT(Model):
    """
    place holder of a mission calss
    """
    def setup(self, engine):
        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .8025

        toclimb = [
            engine['F_{spec}'][0] == 94.971 * units('kN'),
            engine['F_{spec}'][1] == 30.109* units('kN'),
            engine['F_{spec}'][2] == 22.182 * units('kN'),

            engine.state['P_{atm}'][1] == 23.84*units('kPa'),    #36K feet
            engine.state["T_{atm}"][1] == 218*units('K'),
            engine.state['M'][1] == M0,
            engine.engineP['M_2'][1] == M2,
            engine.engineP['M_{2.5}'][1] == M25,
            engine.engineP['hold_{2}'][1] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'][1] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'][1] == 1+.5*(.401)*M0**2,
            ]

        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .8

        cruise = [
            engine.state['P_{atm}'][2] == 23.92*units('kPa'),    #36K feet
            engine.state["T_{atm}"][2] == 219.4*units('K'),
            engine.state['M'][2] == M0,
            engine.engineP['M_2'][2] == M2,
            engine.engineP['M_{2.5}'][2] == M25,
            engine.engineP['hold_{2}'][2] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'][2] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'][2] == 1+.5*(.401)*M0**2,
            ]

        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .2201

        rotation = [
            engine.state['P_{atm}'][0] == 101.325*units('kPa'),
            engine.state["T_{atm}"][0] == 288*units('K'),
            engine.state['M'][0] == M0,
            engine.engineP['M_2'][0] == M2,
            engine.engineP['M_{2.5}'][0] == M25,
            engine.engineP['hold_{2}'][0] == 1+.5*(1.401-1)*M2**2,
            engine.engineP['hold_{2.5}'][0] == 1+.5*(1.401-1)*M25**2,
            engine.engineP['c1'][0] == 1+.5*(.401)*M0**2,

            engine['W_{engine}'] <= 1.1*7870.7*units('lbf'),
            ]

        return rotation, toclimb, cruise

class TestMissionGE90(Model):
    """
    place holder of a mission calss
    """
    def setup(self, engine):
        M2 = .65
        M25 = .6
        M4a = .1025
        M0 = .85

        climb = [
            engine['F_{spec}'][1] == 19600.4*units('lbf'),
            engine['F_{spec}'][0] == 16408.4 * units('lbf'),

            engine.state['P_{atm}'][1] == 23.84*units('kPa'),    #36K feet
            engine.state["T_{atm}"][1] == 218*units('K'),
            engine.state['M'][1] == M0,
            engine.engineP['M_2'][1] == M2,
            engine.engineP['M_{2.5}'][1] == M25,
            engine.engineP['hold_{2}'][1] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'][1] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'][1] == 1+.5*(.401)*M0**2,
            ]

        M0 = .65
        M2 = .6
        M25 = .45
        M4a = .1025

        cruise = [
            engine.state['P_{atm}'][0] == 23.84*units('kPa'),    #36K feet
            engine.state["T_{atm}"][0] == 218*units('K'),
            engine.state['M'][0] == M0,
            engine.engineP['M_2'][0] == M2,
            engine.engineP['M_{2.5}'][0] == M25,
            engine.engineP['hold_{2}'][0] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'][0] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'][0] == 1+.5*(.401)*M0**2,

            engine['W_{engine}'] <= 77399*units('N'),
            ]

        return climb, cruise

class TestMissionD82(Model):
    """
    place holder of a mission calss
    """
    def setup(self, engine):
        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .5

        engineclimb = [
            engine['F_{spec}'][1] == 13.798*units('kN'),
            engine['F_{spec}'][0] == 11.949 * units('kN'),

            engine.state['P_{atm}'][1] == 23.84*units('kPa'),    #36K feet
            engine.state["T_{atm}"][1] == 218*units('K'),
            engine.state['M'][1] == M0,
            engine.engineP['M_{2.5}'][1] == M25,
            engine.engineP['hold_{2}'][1] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'][1] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'][1] == 1+.5*(.401)*M0**2,
            ]

        M2 = .6
        M25 = .6
        M4a = .1025
        M0 = .72

        enginecruise = [
            engine.state['P_{atm}'][0] == 23.84*units('kPa'),    #36K feet
            engine.state["T_{atm}"][0] == 218*units('K'),
            engine.state['M'][0] == M0,
            engine.engineP['M_2'][0] == M2,
            engine.engineP['M_{2.5}'][0] == M25,
            engine.engineP['hold_{2}'][0] == 1+.5*(1.398-1)*M2**2,
            engine.engineP['hold_{2.5}'][0] == 1+.5*(1.354-1)*M25**2,
            engine.engineP['c1'][0] == 1+.5*(.401)*M0**2,

            engine['W_{engine}'] <= 10502.8*units('lbf'),
            ]


        return engineclimb, enginecruise

def test():
    """
    Test the cfm56 engine model
    """
    with Vectorize(2):
        state = TestState()

    Engine.Ttmax = False
    engine = Engine(0, True, 2, state, 0)

    mission = TestMissionCFM(engine)

    substitutions = get_cfm56_subs()

    m = Model((10*engine.engineP.thrustP['TSFC'][0]+engine.engineP.thrustP['TSFC'][1]), [engine, mission], substitutions)
    m.substitutions.update(substitutions)
    sol = m.localsolve(verbosity = 0)

if __name__ == "__main__":
    """
    eng = 0 is CFM56, set N = 2
    eng = 1 is TASOPT 737-800, set N = 3
    eng = 2 is GE90, set N = 2
    eng = 3 is TASOPT D8.2, set N=2
    """
    eng = 1

    if eng == 0 or eng == 2 or eng == 3:
        N = 2
    if eng == 1:
        N = 3

    with Vectorize(N):
        state = TestState()

    engine = Engine(0, True, N, state, eng)

    if eng == 0:
        mission = TestMissionCFM(engine)
        substitutions = get_cfm56_subs()

    if eng == 1:
        mission = TestMissionTASOPT(engine)
        substitutions = get_737800_subs()

    if eng == 2:
        mission = TestMissionGE90(engine)
        substitutions = get_ge90_subs()

    if eng == 3:
        mission = TestMissionD82(engine)
        substitutions = get_D82_subs()

    #dict of initial guesses
    x0 = {
        'W_{engine}': 1e4*units('N'),
        'P_{t_0}': 1e1*units('kPa'),
        'T_{t_0}': 1e3*units('K'),
        'h_{t_0}': 1e6*units('J/kg'),
        'P_{t_{1.8}}': 1e1*units('kPa'),
        'T_{t_{1.8}}': 1e3*units('K'),
        'h_{t_{1.8}}': 1e6*units('J/kg'),
        'P_{T_{2}}': 1e1*units('kPa'),
        'T_{T_{2}}': 1e3*units('K'),
        'h_{T_{2}}': 1e6*units('J/kg'),
        'P_{t_{2.1}}': 1e3*units('K'),
        'T_{t_{2.1}}': 1e3*units('K'),
        'h_{t_{2.1}}': 1e6*units('J/kg'),
        'P_{t_{2.5}}': 1e3*units('kPa'),
        'T_{t_{2.5}}': 1e3*units('K'),
        'h_{t_{2.5}}': 1e6*units('J/kg'),
        'P_{t_3}': 1e4*units('kPa'),
        'T_{t_3}': 1e4*units('K'),
        'h_{t_3}': 1e7*units('J/kg'),
        'P_{t_7}': 1e2*units('kPa'),
        'T_{t_7}': 1e3*units('K'),
        'h_{t_7}': 1e6*units('J/kg'),
        'P_{t_4}': 1e4*units('kPa'),
        'h_{t_4}': 1e7*units('J/kg'),
        'T_{t_4}': 1e4*units('K'),
        'P_{t_{4.1}}': 1e4*units('kPa'),
        'T_{t_{4.1}}': 1e4*units('K'),
        'h_{t_{4.1}}': 1e7*units('J/kg'),
        'T_{4.1}': 1e4*units('K'),
        'f': 1e-2,
        'P_{4a}': 1e4*units('kPa'),
        'h_{t_{4.5}}': 1e6*units('J/kg'),
        'P_{t_{4.5}}': 1e3*units('kPa'),
        'T_{t_{4.5}}': 1e4*units('K'),
        'P_{t_{4.9}}': 1e2*units('kPa'),
        'T_{t_{4.9}}': 1e3*units('K'),
        'h_{t_{4.9}}': 1e6*units('J/kg'),
        '\\pi_{HPT}': 1e-1,
        '\\pi_{LPT}': 1e-1,
        'P_{t_5}': 1e2*units('kPa'),
        'T_{t_5}': 1e3*units('K'),
        'h_{t_5}': 1e6*units('J/kg'),
        'P_{8}': 1e2*units('kPa'),
        'P_{t_8}': 1e2*units('kPa'),
        'h_{t_8}': 1e6*units('J/kg'),
        'h_{8}': 1e6*units('J/kg'),
        'T_{t_8}': 1e3*units('K'),
        'T_{8}': 1e3*units('K'),
        'P_{6}': 1e2*units('kPa'),
        'P_{t_6}': 1e2*units('kPa'),
        'T_{t_6': 1e3*units('K'),
        'h_{t_6}': 1e6*units('J/kg'),
        'h_{6}': 1e6*units('J/kg'),
        'F_{8}': 1e2 * units('kN'),
        'F_{6}': 1e2 * units('kN'),
        'F': 1e2 * units('kN'),
        'F_{sp}': 1e-1,
        'TSFC': 1e-1,
        'I_{sp}': 1e4*units('s'),
        'u_{6}': 1e3*units('m/s'),
        'u_{8}': 1e3*units('m/s'),
        'm_{core}': 1e2*units('kg/s'),
        'm_{fan}': 1e3*units('kg/s'),
        '\\alpha': 1e1,
        '\\alpha_{+1}': 1e1,
        'm_{total}': 1e3*units('kg/s'),
        'T_{2}': 1e3*units('K'),
        'P_{2}': 1e2*units('kPa'),
        'u_{2}': 1e3*units('m/s'),
        'h_{2}': 1e6*units('J/kg'),
        'T_{2.5}': 1e3*units('K'),
        'P_{2.5}': 1e2*units('kPa'),
        'u_{2.5}': 1e3*units('m/s'),
        'h_{2.5}': 1e6*units('J/kg'),
        'P_{7}': 1e2*units('kPa'),
        'T_{7}': 1e3*units('K'),
        'u_{7}': 1e3*units('m/s'),
        'P_{5}': 1e2*units('kPa'),
        'T_{5}': 1e3*units('K'),
        'u_{5}': 1e3*units('m/s'),
        'P_{atm}': 1e2*units('kPa'),
        'T_{atm}': 1e3*units('K'),
        'V': 1e3*units('knot'),
        'a': 1e3*units('m/s'),
    }

    #select the proper objective based off of the number of flight segments
    if eng == 0 or eng == 2 or eng == 3:
        m = Model((10*engine.engineP.thrustP['TSFC'][0]+engine.engineP.thrustP['TSFC'][1]), [engine, mission], substitutions, x0=x0)
    if eng == 1:
        m = Model((10*engine.engineP.thrustP['TSFC'][2]+engine.engineP.thrustP['TSFC'][1]+engine.engineP.thrustP['TSFC'][0]), [engine, mission], substitutions, x0=x0)

    #update substitutions and solve
    m.substitutions.update(substitutions)
    sol = m.localsolve(solver = 'mosek', verbosity = 0)

    #print out various percent differences in TSFC and engine areas
    if eng == 0:
        tocerror = 100*(mag(sol('TSFC')[1]) - .6941)/.6941
        cruiseerror = 100*(mag(sol('TSFC')[0]) - .6793)/.6793
        weighterror =  100*(mag(sol('W_{engine}').to('lbf'))-5216)/5216

        print "Cruise error"
        print cruiseerror
        print "TOC error"
        print tocerror
        print "Weight Error"
        print weighterror

    if eng == 1:
        rotationerror = 100*(mag(sol('TSFC')[0]) - .48434)/.48434
        tocerror = 100*(mag(sol('TSFC')[1]) - .65290)/.65290
        cruiseerror = 100*(mag(sol('TSFC')[2]) - .64009)/.64009

        print rotationerror, tocerror, cruiseerror

##        print 100*(mag(sol('A_{2}').to('m^2'))-1.6026)/1.6026
##        print 100*(mag(sol('A_{7}').to('m^2'))-.7423)/.7423
##        print 100*(mag(sol('A_{5}').to('m^2'))-.2262)/.2262
        print "----weight---"
        print 100*(mag(sol('W_{engine}').to('lbf'))-7870.7)/7870.7

        print "TO Tt4.1"
        print 100*(mag(sol('T_{t_{4.1}}')[0]) - 1658.7)/1658.7
        print "TOC Tt4.1"
        print 100*(mag(sol('T_{t_{4.1}}')[1]) - 1605.4)/1605.4
        print "Cruise Tt4.1"
        print 100*(mag(sol('T_{t_{4.1}}')[2]) - 1433.8)/1433.8

        print "Cooling deltas"
        print "TO"
        print 100*(mag(sol('T_{t_4}')[0]-sol('T_{t_{4.1}}')[0]) - 174.3)/174.3
        print "TOC"
        print 100*(mag(sol('T_{t_4}')[1]-sol('T_{t_{4.1}}')[1]) - 178.4)/178.4
        print "Cruise"
        print 100*(mag(sol('T_{t_4}')[2]-sol('T_{t_{4.1}}')[2]) - 153.2)/153.2

    if eng == 2:
        tocerror = 100*(mag(sol('TSFC')[1]) - 0.5846)/0.5846
        cruiseerror = 100*(mag(sol('TSFC')[0]) - 0.5418)/0.5418
        weighterror =  100*(mag(sol('W_{engine}').to('lbf'))-17400)/17400

        print tocerror, cruiseerror, weighterror


#code for estimating on design parameters
##Pt0 = 50
##Tt0 = 250
##Pt3 = Pt0*lpc*fan*hpc
##Pt21 = fan * Pt0
##Pt25 = Pt0 * fan * lpc
##
##Tt21 = Tt0 * (fan)**(.4/(1.4*.9153))
##Tt25 = Tt21 * (lpc)**(.4/(1.4*.9037))
##Tt3 = Tt25 * (hpc)**(.4/(1.4*.9247))
##
##Tt41 = 1400
##
##Tt45 = Tt41 - (Tt3 - Tt25)
##
##Tt49 = Tt45 - (Tt25 - Tt21)
##
##piHPT = (Tt45/Tt41)**(.9121*1.4/.4)
##
##piLPT = (Tt49/Tt45)**(.9228*1.4/.4)
##
##Pt45 = piHPT * Pt3
