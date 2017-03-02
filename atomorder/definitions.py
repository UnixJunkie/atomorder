
class Constants(object):
    """
    Constants()

    Constructor for constants used in the script


    Attributes
    ----------
    bond_length_limits: dict
        Dictionary of loose and tight distance limits on bond lengths
    number_bonds: dict
        Number of bonds the supported atom types can form
    monovalent: list
        Monovalent atom types

    """
    def __init__(self):

        # Found from analyzing the CCDC 2016 database.
        # loose_lower, lower, loose_upper, upper
        self.bond_length_limits = {("As","As"): (2.20, 2.30, 2.65, 2.80),
                              ("As","Br"): (2.20, 2.30, 3.30, 3.40),
                              ("As","Cl"): (2.10, 2.15, 2.40, 3.30),
                              ("As","C" ): (1.75, 1.80, 2.10, 2.20),
                              ("As","F" ): (1.50, 1.60, 1.80, 2.10),
                              ("As","I" ): (2.30, 2.40, 3.70, 3.80),
                              ("As","N" ): (1.60, 1.70, 2.05, 2.70),
                              ("As","O" ): (1.40, 1.60, 2.00, 2.30),
                              ("As","P" ): (2.10, 2.20, 2.40, 2.60),
                              ("As","S" ): (1.90, 2.00, 2.40, 3.10),
                              ("Br","Br"): (2.20, 2.20, 2.80, 4.00),
                              ("Br","C" ): (1.75, 1.80, 2.00, 2.10),
                              ("Br","I" ): (2.50, 2.55, 3.00, 3.50),
                              ("Br","P" ): (2.00, 2.10, 2.70, 3.00),
                              ("C" ,"Cl"): (1.60, 1.65, 1.85, 2.00),
                              ("C" ,"C" ): (1.10, 1.25, 1.70, 1.80),
                              ("C" ,"F" ): (1.20, 1.25, 1.45, 1.50),
                              ("C" ,"H" ): (0.85, 0.95, 1.15, 1.25),
                              ("C" ,"I" ): (1.90, 2.00, 2.20, 2.25),
                              ("C" ,"N" ): (1.00, 1.10, 1.60, 1.70),
                              ("C" ,"O" ): (1.00, 1.15, 1.50, 1.60),
                              ("C" ,"P" ): (1.45, 1.65, 1.95, 2.00),
                              ("C" ,"S" ): (1.50, 1.60, 1.90, 2.00),
                              ("Cl","I" ): (2.30, 2.35, 2.75, 3.10),
                              ("Cl","N" ): (1.60, 1.65, 1.80, 1.90),
                              ("Cl","O" ): (1.20, 1.30, 1.50, 1.60),
                              ("Cl","P" ): (1.90, 1.95, 2.20, 2.40),
                              ("Cl","S" ): (1.90, 1.95, 2.45, 3.10),
                              ("F" ,"I" ): (1.80, 1.90, 2.15, 3.00),
                              ("F" ,"P" ): (1.40, 1.50, 1.65, 1.70),
                              ("F" ,"S" ): (1.40, 1.45, 1.75, 1.80),
                              ("H" ,"N" ): (0.80, 0.95, 1.10, 1.25),
                              ("H" ,"O" ): (0.70, 0.85, 1.10, 1.30),
                              ("I" ,"I" ): (2.60, 2.70, 3.20, 3.60),
                              ("I" ,"N" ): (1.90, 1.95, 2.55, 2.65),
                              ("I" ,"O" ): (1.55, 1.60, 2.60, 3.00),
                              ("I" ,"P" ): (2.30, 2.35, 2.60, 3.00),
                              ("I" ,"S" ): (2.30, 2.40, 2.95, 3.25),
                              ("N" ,"N" ): (1.00, 1.10, 1.50, 1.60),
                              ("N" ,"O" ): (1.10, 1.15, 1.50, 1.60),
                              ("N" ,"P" ): (1.40, 1.50, 1.80, 2.10),
                              ("N" ,"S" ): (1.40, 1.50, 1.75, 1.85),
                              ("O" ,"O" ): (1.20, 1.25, 1.55, 1.60),
                              ("O" ,"P" ): (1.35, 1.40, 1.80, 1.90),
                              ("O" ,"S" ): (1.35, 1.40, 1.65, 1.80),
                              ("P" ,"P" ): (1.95, 2.00, 2.35, 2.60),
                              ("P" ,"S" ): (1.75, 1.85, 2.20, 2.30),
                              ("S" ,"S" ): (1.90, 2.00, 2.40, 2.60)
                             }
        # hydrogen bond lengths were taken from neutron diffraction data that
        # didn't have many S-H hits, so guesstimate them
        self.bond_length_limits[("H","S")] = (1.2,1.3,1.4,1.5)

        # make inverse atom order
        for key, value in self.bond_length_limits.items():
            self.bond_length_limits[key[::-1]] = value

        # number of bonds each atom type commonly form
        self.number_bonds = {"As": [3,4],
                        "Br": [1],
                        "C" : [2,3,4],
                        "Cl": [1],
                        "F" : [1],
                        "H" : [1],
                        "I" : [1],
                        "N" : [1,2,3,4],
                        "O" : [1,2],
                        "P" : [3],
                        "S" : [1,2,3,4]
                        }
        
        # monovalent atoms
        self.monovalent = ["Br","Cl","F","H","I"]

