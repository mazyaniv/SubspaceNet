"""Subspace-Net 
Details
----------
Name: models.py
Authors: Dor Haim Shmuel
Created: 01/10/21
Edited: 02/06/23

Purpose:
--------
This script defines the tested NN-models and the model-based DL models, which used for simulation.
The implemented models:
    * DeepRootMUSIC: model-based deep learning algorithm as described in:
        [1] D. H. Shmuel, J. P. Merkofer, G. Revach, R. J. G. van Sloun and N. Shlezinger,
        "Deep Root Music Algorithm for Data-Driven Doa Estimation," ICASSP 2023 - 
        2023 IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP),
        Rhodes Island, Greece, 2023, pp. 1-5, doi: 10.1109/ICASSP49357.2023.10096504.
        
    * SubspaceNet: model-based deep learning algorithm as described in:
        [2] "SubspaceNet: Deep Learning-Aided Subspace methods for DoA Estimation".
    
    * DA-MUSIC: Deep Augmented MUSIC model-based deep learning algorithm as described in
        [3] J. P. Merkofer, G. Revach, N. Shlezinger, and R. J. van Sloun, “Deep
        augmented MUSIC algorithm for data-driven DoA estimation,” in IEEE
        International Conference on Acoustics, Speech and Signal Processing
        (ICASSP), 2022, pp. 3598-3602."
        
    * DeepCNN: Deep learning algorithm as described in:
        [4] G. K. Papageorgiou, M. Sellathurai, and Y. C. Eldar, “Deep networks
        for direction-of-arrival estimation in low SNR,” IEEE Trans. Signal
        Process., vol. 69, pp. 3714-3729, 2021.

Functions:
----------
This script also includes the implementation of Root-MUSIC algorithm, as it is written using Pytorch library,
for the usage of src.models: SubspaceNet implementation.
"""

# Imports
import numpy as np
import torch
import torch.nn as nn
import numpy as np
import scipy as sc
import warnings
from src.utils import gram_diagonal_overload, device
from src.utils import sum_of_diags_torch, find_roots_torch
import time

warnings.simplefilter("ignore")


# Constants
# device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class ModelGenerator(object):
    """
    Generates an instance of the desired model, according to model configuration parameters.
    """

    def __init__(self):
        """
        Initialize ModelParams object.
        """
        self.model_type = None
        self.field_type = None
        self.diff_method = None
        self.tau = None
        self.model = None

    def set_field_type(self, field_type: str = None):
        """

        Args:
            field_type:

        Returns:

        """
        if field_type.lower() == "near":
            self.field_type = "Near"
        elif field_type.lower() == "far":
            self.field_type = "Far"
        else:
            raise Exception(f"ModelParams.set_field_type:"
                            f" unrecognized {field_type} as field type, available options are Near or Far.")
        return self

    def set_tau(self, tau: int = None):
        """
        Set the value of tau parameter for SubspaceNet model.

        Parameters:
            tau (int): The number of lags.

        Returns:
            ModelParams: The updated ModelParams object.

        Raises:
            ValueError: If tau parameter is not provided for SubspaceNet model.
        """
        if self.model_type.startswith("SubspaceNet"):
            if not isinstance(tau, int):
                raise ValueError(
                    "ModelParams.set_tau: tau parameter must be provided for SubspaceNet model"
                )
            self.tau = tau
        return self

    def set_diff_method(self, diff_method: str = "root_music"):
        """
        Set the differentiation method for SubspaceNet model.

        Parameters:
            diff_method (str): The differantiable subspace method ("esprit" or "root_music").

        Returns:
            ModelParams: The updated ModelParams object.

        Raises:
            ValueError: If the diff_method is not defined for SubspaceNet model.
        """
        if self.model_type.startswith("SubspaceNet"):
            if self.field_type.startswith("Far"):
                if diff_method not in ["esprit", "root_music"]:
                    raise ValueError(
                        f"ModelParams.set_diff_method:"
                        f" {diff_method} is not defined for SubspaceNet model on {self.field_type} scenario")
                self.diff_method = diff_method
            elif self.field_type.startswith("Near"):
                if diff_method not in ["music_2D"]:
                    raise ValueError(f"ModelParams.set_diff_method: "
                                     f"{diff_method} is not defined for SubspaceNet model on {self.field_type} scenario")
                self.diff_method = diff_method
        return self

    def set_model_type(self, model_type: str):
        """
        Set the model type.

        Parameters:
            model_type (str): The model type.

        Returns:
            ModelParams: The updated ModelParams object.

        Raises:
            ValueError: If model type is not provided.
        """
        if not isinstance(model_type, str):
            raise ValueError(
                "ModelParams.set_model_type: model type has not been provided"
            )
        self.model_type = model_type
        return self

    def set_model(self, system_model_params):
        """
        Set the model based on the model type and system model parameters.

        Parameters:
            system_model_params (SystemModelParams): The system model parameters.

        Returns:
            ModelParams: The updated ModelParams object.

        Raises:
            Exception: If the model type is not defined.
        """
        if self.model_type.startswith("DA-MUSIC"):
            self.model = DeepAugmentedMUSIC(
                N=system_model_params.N,
                T=system_model_params.T,
                M=system_model_params.M,
            )
        elif self.model_type.startswith("DeepCNN"):
            self.model = DeepCNN(N=system_model_params.N, grid_size=361)
        elif self.model_type.startswith("SubspaceNet"):
            self.model = SubspaceNet(tau=self.tau,
                                     M=system_model_params.M,
                                     N=system_model_params.N,
                                     diff_method=self.diff_method,
                                     field_type=self.field_type)
        else:
            raise Exception(f"ModelGenerator.set_model: Model type {self.model_type} is not defined")

        return self


class DeepRootMUSIC(nn.Module):
    """DeepRootMUSIC is model-based deep learning model for DOA estimation problem.

    Attributes:
    -----------
        M (int): Number of sources.
        tau (int): Number of auto-correlation lags.
        conv1 (nn.Conv2d): Convolution layer 1.
        conv2 (nn.Conv2d): Convolution layer 2.
        conv3 (nn.Conv2d): Convolution layer 3.
        deconv1 (nn.ConvTranspose2d): De-convolution layer 1.
        deconv2 (nn.ConvTranspose2d): De-convolution layer 2.
        deconv3 (nn.ConvTranspose2d): De-convolution layer 3.
        DropOut (nn.Dropout): Dropout layer.
        LeakyReLU (nn.LeakyReLU): Leaky reLu activation function, with activation_value.

    Methods:
    --------
        anti_rectifier(X): Applies the anti-rectifier operation to the input tensor.
        forward(Rx_tau): Performs the forward pass of the SubspaceNet.
        gram_diagonal_overload(Kx, eps): Applies Gram operation and diagonal loading to a complex matrix.

    """

    def __init__(self, tau: int, activation_value: float):
        """Initializes the SubspaceNet model.

        Args:
        -----
            tau (int): Number of auto-correlation lags.
            activation_value (float): Value for the activation function.

        """
        super(DeepRootMUSIC, self).__init__()
        self.tau = tau
        self.conv1 = nn.Conv2d(self.tau, 16, kernel_size=2)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=2)
        self.conv3 = nn.Conv2d(32, 64, kernel_size=2)
        self.deconv1 = nn.ConvTranspose2d(64, 32, kernel_size=2)
        self.deconv2 = nn.ConvTranspose2d(32, 16, kernel_size=2)
        self.deconv3 = nn.ConvTranspose2d(16, 1, kernel_size=2)
        self.LeakyReLU = nn.LeakyReLU(activation_value)
        self.DropOut = nn.Dropout(0.2)

    def forward(self, Rx_tau: torch.Tensor):
        """
        Performs the forward pass of the DeepRootMUSIC.

        Args:
        -----
            Rx_tau (torch.Tensor): Input tensor of shape [Batch size, tau, 2N, N].

        Returns:
        --------
            doa_prediction (torch.Tensor): The predicted direction-of-arrival (DOA) for each batch sample.
            doa_all_predictions (torch.Tensor): All DOA predictions for each root, over all batches.
            roots_to_return (torch.Tensor): The unsorted roots.
            Rz (torch.Tensor): Surrogate covariance matrix.

        """
        # Rx_tau shape: [Batch size, tau, 2N, N]
        self.N = Rx_tau.shape[-1]
        self.batch_size = Rx_tau.shape[0]
        ## Architecture flow ##
        # CNN block #1
        x = self.conv1(Rx_tau)
        x = self.LeakyReLU(x)
        # CNN block #2
        x = self.conv2(x)
        x = self.LeakyReLU(x)
        # CNN block #3
        x = self.conv3(x)
        x = self.LeakyReLU(x)
        # DCNN block #1
        x = self.deconv1(x)
        x = self.LeakyReLU(x)
        # DCNN block #2
        x = self.deconv2(x)
        x = self.LeakyReLU(x)
        # DCNN block #3
        x = self.DropOut(x)
        Rx = self.deconv3(x)
        # Reshape Output shape: [Batch size, 2N, N]
        Rx_View = Rx.view(Rx.size(0), Rx.size(2), Rx.size(3))
        # Real and Imaginary Reconstruction
        Rx_real = Rx_View[:, : self.N, :]  # Shape: [Batch size, N, N])
        Rx_imag = Rx_View[:, self.N:, :]  # Shape: [Batch size, N, N])
        Kx_tag = torch.complex(Rx_real, Rx_imag)  # Shape: [Batch size, N, N])
        # Apply Gram operation diagonal loading
        Rz = gram_diagonal_overload(Kx_tag, eps=1)  # Shape: [Batch size, N, N]
        # Feed surrogate covariance to Root-MUSIC algorithm
        doa_prediction, doa_all_predictions, roots = root_music(
            Rz, self.M, self.batch_size
        )
        return doa_prediction, doa_all_predictions, roots, Rz


# TODO: inherit SubspaceNet from DeepRootMUSIC
class SubspaceNet(nn.Module):
    """SubspaceNet is model-based deep learning model for generalizing DOA estimation problem,
        over subspace methods.

    Attributes:
    -----------
        M (int): Number of sources.
        tau (int): Number of auto-correlation lags.
        N (int):
        diff_method (str):
        field_type (str):
        conv1 (nn.Conv2d): Convolution layer 1.
        conv2 (nn.Conv2d): Convolution layer 2.
        conv3 (nn.Conv2d): Convolution layer 3.
        deconv1 (nn.ConvTranspose2d): De-convolution layer 1.
        deconv2 (nn.ConvTranspose2d): De-convolution layer 2.
        deconv3 (nn.ConvTranspose2d): De-convolution layer 3.
        DropOut (nn.Dropout): Dropout layer.
        ReLU (nn.ReLU): ReLU activation function.

    Methods:
    --------
        anti_rectifier(X): Applies the anti-rectifier operation to the input tensor.
        forward(Rx_tau): Performs the forward pass of the SubspaceNet.
        gram_diagonal_overload(Kx, eps): Applies Gram operation and diagonal loading to a complex matrix.

    """

    def __init__(self, tau: int, M: int, N: int, diff_method: str = "root_music", field_type: str = "Far"):
        """Initializes the SubspaceNet model.

        Args:
        -----
            tau (int): Number of auto-correlation lags.
            M (int): Number of sources.

        """
        super(SubspaceNet, self).__init__()
        self.M = M
        self.tau = tau
        self.N = N
        self.diff_method = None
        self.field_type = None
        self.conv1 = nn.Conv2d(self.tau, 16, kernel_size=2)
        self.conv2 = nn.Conv2d(32, 32, kernel_size=2)
        self.conv3 = nn.Conv2d(64, 64, kernel_size=2)
        self.fully_linear1 = nn.Linear(128 * (2 * N - 3) * (N - 3), 128)
        self.fully_linear2 = nn.Linear(128, 32)
        self.fully_linear3 = nn.Linear(32, 128)
        self.fully_linear4 = nn.Linear(128, 128 * (2 * N - 3) * (N - 3))
        self.deconv2 = nn.ConvTranspose2d(128, 32, kernel_size=2)
        self.deconv3 = nn.ConvTranspose2d(64, 16, kernel_size=2)
        self.deconv4 = nn.ConvTranspose2d(32, 1, kernel_size=2)
        self.DropOut = nn.Dropout(0.2)
        self.ReLU = nn.ReLU()
        # Set the field type scenario: Far or Near.
        self.set_field_type(field_type)
        # Set the subspace method for training
        self.set_diff_method(diff_method)
        self.search_grid = None
        self.theta_range = None
        self.distance_range = None
        if diff_method.startswith("music_2D"):
            wavelength = 1
            spacing = wavelength / 2
            diemeter = (N - 1) * spacing
            franhofer = np.floor(2 * diemeter ** 2 / wavelength)
            fersnel = np.ceil(0.62 * (diemeter ** 3 / wavelength) ** 0.5)
            self.array = torch.linspace(0, N, N)
            self.theta_range = torch.linspace(-1 * torch.pi / 2, torch.pi / 2, 90, dtype=torch.float, device=device)
            self.distance_range = torch.arange(np.floor(fersnel), np.round(franhofer + 0.5), 1, dtype=torch.float, device=device)
            self.search_grid = self.set_search_grid(self.theta_range, self.distance_range).type(
                torch.complex64).detach()

    def set_field_type(self, field_type: str):
        """

        Args:
            field_type:

        Returns:

        """
        if field_type.lower() == "far":
            self.field_type = "Far"
        elif field_type.lower() == "near":
            self.field_type = "Near"
        else:
            raise Exception(f"Unrecognized field type {field_type}, possible options are Far or Near.")

    def set_diff_method(self, diff_method: str):
        """Sets the differentiable subspace method for training subspaceNet.
            Options: "root_music", "esprit"

        Args:
        -----
            diff_method (str): differentiable subspace method.

        Raises:
        -------
            Exception: Method diff_method is not defined for SubspaceNet
        """
        if self.field_type == "Far":
            if diff_method.startswith("root_music"):
                self.diff_method = root_music
            elif diff_method.startswith("esprit"):
                self.diff_method = esprit
            else:
                raise Exception(f"SubspaceNet.set_diff_method:"
                                f" Method {diff_method} is not defined for SubspaceNet in {self.field_type} scenario")
        elif self.field_type == "Near":
            if diff_method.startswith("music_2D"):
                self.diff_method = music_2d
            else:
                raise Exception(f"SubspaceNet.set_diff_method:"
                                f" Method {diff_method} is not defined for SubspaceNet in {self.field_type} scenario")

    def anti_rectifier(self, X):
        """Applies the anti-rectifier operation to the input tensor.

        Args:
        -----
            X (torch.Tensor): Input tensor.

        Returns:
        --------
            torch.Tensor: Output tensor after applying the anti-rectifier operation.

        """
        return torch.cat((self.ReLU(X), self.ReLU(-X)), 1)

    def set_search_grid(self, theta: torch.Tensor, distances: torch.Tensor) -> torch.Tensor:
        """

        Args:
            theta:
            distances:

        Returns:

        """
        theta = torch.atleast_1d(theta).unsqueeze(1)
        distances = torch.atleast_1d(distances).unsqueeze(1)

        array = torch.tile(self.array.unsqueeze(1), (1, self.N))
        array_square = array.pow(2)

        first_order = array @ torch.tile(torch.sin(theta), (1, self.N)).t()
        first_order = first_order.unsqueeze(2).expand(-1, -1, len(distances))

        second_order = -0.5 * torch.div(torch.pow(torch.cos(theta), 2), distances.t())
        second_order = second_order.unsqueeze(2).expand(-1, -1, self.N)
        second_order = torch.einsum("ij, jkl -> ilk", array_square, second_order.permute(2, 1, 0))

        time_delay = first_order + second_order

        return torch.exp(2 * -1j * np.pi * time_delay)

    def forward(self, Rx_tau: torch.Tensor, is_soft=True):
        """
        Performs the forward pass of the SubspaceNet.

        Args:
        -----
            Rx_tau (torch.Tensor): Input tensor of shape [Batch size, tau, 2N, N].

        Returns:
        --------
            doa_prediction (torch.Tensor): The predicted direction-of-arrival (DOA) for each batch sample.
            doa_all_predictions (torch.Tensor): All DOA predictions for each root, over all batches.
            roots_to_return (torch.Tensor): The unsorted roots.
            Rz (torch.Tensor): Surrogate covariance matrix.

        """
        # Rx_tau shape: [Batch size, tau, 2N, N]
        self.N = Rx_tau.shape[-1]
        self.batch_size = Rx_tau.shape[0]
        ## Architecture flow ##
        # CNN block #1
        x = self.conv1(Rx_tau)
        x = self.anti_rectifier(x)
        # CNN block #2
        x = self.conv2(x)
        x = self.anti_rectifier(x)
        # CNN block #3
        x = self.conv3(x)
        x = self.anti_rectifier(x)

        # # fully connected
        old_shape = x.shape
        x = self.fully_linear1(x.view(x.shape[0], -1))
        # x = self.fully_linear2(x)
        # x = self.fully_linear3(x)
        x = self.fully_linear4(x)
        # DCNN block #2
        x = self.deconv2(x.view(old_shape))
        x = self.anti_rectifier(x)
        # DCNN block #3
        x = self.deconv3(x)
        x = self.anti_rectifier(x)
        # DCNN block #4
        x = self.DropOut(x)
        Rx = self.deconv4(x)
        # Reshape Output shape: [Batch size, 2N, N]
        Rx_View = Rx.view(Rx.size(0), Rx.size(2), Rx.size(3))
        # Real and Imaginary Reconstruction
        Rx_real = Rx_View[:, : self.N, :]  # Shape: [Batch size, N, N])
        Rx_imag = Rx_View[:, self.N:, :]  # Shape: [Batch size, N, N])
        Kx_tag = torch.complex(Rx_real, Rx_imag)  # Shape: [Batch size, N, N])
        # Apply Gram operation diagonal loading
        Rz = gram_diagonal_overload(
            Kx=Kx_tag, eps=1, batch_size=self.batch_size
        )  # Shape: [Batch size, N, N]
        # Feed surrogate covariance to the differentiable subspace algorithm

        if self.field_type == "Far":
            method_output = self.diff_method(Rz, self.M, self.batch_size)
            if isinstance(method_output, tuple):
                # Root MUSIC output
                doa_prediction, doa_all_predictions, roots = method_output
            else:
                # Esprit output
                doa_prediction = method_output
                doa_all_predictions, roots = None, None
            return doa_prediction, doa_all_predictions, roots, Rz

        elif self.field_type == "Near":
            doa_prediction, distance_prediction = self.diff_method(Rz,
                                                                   self.M,
                                                                   self.search_grid,
                                                                   self.theta_range,
                                                                   self.distance_range,
                                                                   is_soft=is_soft)
            return doa_prediction, distance_prediction, Rz


class SubspaceNetEsprit(SubspaceNet):
    """SubspaceNet is model-based deep learning model for generalizing DOA estimation problem,
        over subspace methods.
        SubspaceNetEsprit is based on the ability to perform back-propagation using ESPRIT algorithm,
        instead of RootMUSIC.

    Attributes:
    -----------
        M (int): Number of sources.
        tau (int): Number of auto-correlation lags.

    Methods:
    --------
        forward(Rx_tau): Performs the forward pass of the SubspaceNet.

    """

    def __init__(self, tau: int, M: int):
        super().__init__(tau, M)

    def forward(self, Rx_tau: torch.Tensor):
        """
        Performs the forward pass of the SubspaceNet.

        Args:
        -----
            Rx_tau (torch.Tensor): Input tensor of shape [Batch size, tau, 2N, N].

        Returns:
        --------
            doa_prediction (torch.Tensor): The predicted direction-of-arrival (DOA) for each batch sample.
            Rz (torch.Tensor): Surrogate covariance matrix.

        """
        # Rx_tau shape: [Batch size, tau, 2N, N]
        self.N = Rx_tau.shape[-1]
        self.batch_size = Rx_tau.shape[0]
        ## Architecture flow ##
        # CNN block #1
        x = self.conv1(Rx_tau)
        x = self.anti_rectifier(x)
        # CNN block #2
        x = self.conv2(x)
        x = self.anti_rectifier(x)
        # CNN block #3
        x = self.conv3(x)
        x = self.anti_rectifier(x)
        # DCNN block #1
        x = self.deconv2(x)
        x = self.anti_rectifier(x)
        # DCNN block #2
        x = self.deconv3(x)
        x = self.anti_rectifier(x)
        # DCNN block #3
        x = self.DropOut(x)
        Rx = self.deconv4(x)
        # Reshape Output shape: [Batch size, 2N, N]
        Rx_View = Rx.view(Rx.size(0), Rx.size(2), Rx.size(3))
        # Real and Imaginary Reconstruction
        Rx_real = Rx_View[:, : self.N, :]  # Shape: [Batch size, N, N])
        Rx_imag = Rx_View[:, self.N:, :]  # Shape: [Batch size, N, N])
        Kx_tag = torch.complex(Rx_real, Rx_imag)  # Shape: [Batch size, N, N])
        # Apply Gram operation diagonal loading
        Rz = gram_diagonal_overload(
            Kx=Kx_tag, eps=1, batch_size=self.batch_size
        )  # Shape: [Batch size, N, N]
        # Feed surrogate covariance to Esprit algorithm
        doa_prediction = esprit(Rz, self.M, self.batch_size)
        return doa_prediction, Rz


class DeepAugmentedMUSIC(nn.Module):
    """DeepAugmentedMUSIC is a model-based deep learning model for Direction of Arrival (DOA) estimation.

    Attributes:
        N (int): Number of sensors.
        T (int): Number of observations.
        M (int): Number of sources.
        angels (torch.Tensor): Tensor containing angles from -pi/2 to pi/2.
        input_size (int): Size of the input.
        hidden_size (int): Size of the hidden layer.
        rnn (nn.GRU): Recurrent neural network module.
        fc (nn.Linear): Fully connected layer.
        fc1 (nn.Linear): Fully connected layer.
        fc2 (nn.Linear): Fully connected layer.
        fc3 (nn.Linear): Fully connected layer.
        ReLU (nn.ReLU): Rectified Linear Unit activation function.
        DropOut (nn.Dropout): Dropout layer.
        BatchNorm (nn.BatchNorm1d): Batch normalization layer.
        sv (torch.Tensor): Steering vector.

    Methods:
        steering_vec(): Computes the steering vector based on the specified parameters.
        spectrum_calculation(Un: torch.Tensor): Calculates the MUSIC spectrum.
        pre_MUSIC(Rz: torch.Tensor): Applies the MUSIC operation for generating the spectrum.
        forward(X: torch.Tensor): Performs the forward pass of the DeepAugmentedMUSIC model.
    """

    def __init__(self, N: int, T: int, M: int):
        """Initializes the DeepAugmentedMUSIC model.

        Args:
        -----
            N (int): Number of sensors.
            M (int): Number of sources.
            T (int): Number of observations.
        """
        super(DeepAugmentedMUSIC, self).__init__()
        self.N, self.T, self.M = N, T, M
        self.angels = torch.linspace(-1 * np.pi / 2, np.pi / 2, 361)
        self.input_size = 2 * self.N
        self.hidden_size = 2 * self.N
        self.rnn = nn.GRU(self.input_size, self.hidden_size, batch_first=True)
        self.fc = nn.Linear(self.hidden_size, self.hidden_size * self.N)
        self.fc1 = nn.Linear(self.angels.shape[0], self.hidden_size)
        self.fc2 = nn.Linear(self.hidden_size, self.hidden_size)
        self.fc3 = nn.Linear(self.hidden_size, self.M)
        self.ReLU = nn.ReLU()
        self.DropOut = nn.Dropout(0.25)
        self.BatchNorm = nn.BatchNorm1d(self.T)
        self.sv = self.steering_vec()
        # Weights initialization
        nn.init.xavier_uniform(self.fc.weight)
        nn.init.xavier_uniform(self.fc1.weight)
        nn.init.xavier_uniform(self.fc2.weight)
        nn.init.xavier_uniform(self.fc3.weight)

    def steering_vec(self):
        """Computes the ideal steering vector based on the specified parameters.
            equivalent to src.system_model.steering_vec method, but support pyTorch.

        Returns:
        --------
            tensor.Torch: the steering vector
        """
        sv = []
        for angle in self.angels:
            a = torch.exp(
                -1 * 1j * np.pi * torch.linspace(0, self.N - 1, self.N) * np.sin(angle)
            )
            sv.append(a)
        return torch.stack(sv, dim=0)

    def spectrum_calculation(self, Un: torch.Tensor):
        spectrum_equation = []
        for i in range(self.angels.shape[0]):
            spectrum_equation.append(
                torch.real(
                    torch.conj(self.sv[i]).T @ Un @ torch.conj(Un).T @ self.sv[i]
                )
            )
        spectrum_equation = torch.stack(spectrum_equation, dim=0)
        spectrum = 1 / spectrum_equation

        return spectrum, spectrum_equation

    def pre_MUSIC(self, Rz: torch.Tensor):
        """Applies the MUSIC operration for generating spectrum

        Args:
            Rz (torch.Tensor): Generated covariance matrix

        Returns:
            torch.Tensor: The generated MUSIC spectrum
        """
        spectrum = []
        bs_Rz = Rz
        for iter in range(self.batch_size):
            R = bs_Rz[iter]
            # Extract eigenvalues and eigenvectors using EVD
            _, eigenvectors = torch.linalg.eig(R)
            # Noise subspace as the eigenvectors which associated with the M first eigenvalues
            Un = eigenvectors[:, self.M:]
            # Calculate MUSIC spectrum
            spectrum.append(self.spectrum_calculation(Un)[0])
        return torch.stack(spectrum, dim=0)

    def forward(self, X: torch.Tensor):
        """
        Performs the forward pass of the DeepAugmentedMUSIC model.

        Args:
        -----
            X (torch.Tensor): Input tensor.

        Returns:
        --------
            torch.Tensor: The estimated DOA.
        """
        # X shape == [Batch size, N, T]
        self.BATCH_SIZE = X.shape[0]
        ## Architecture flow ##
        # decompose X and concatenate real and imaginary part
        X = torch.cat(
            (torch.real(X), torch.imag(X)), 1
        )  # Shape ==  [Batch size, 2N, T]
        # Reshape Output shape: [Batch size, T, 2N]
        X = X.view(X.size(0), X.size(2), X.size(1))
        # Apply batch normalization
        X = self.BatchNorm(X)
        # GRU Clock
        gru_out, hn = self.rnn(X)
        Rx = gru_out[:, -1]
        # Reshape Output shape: [Batch size, 1, 2N]
        Rx = Rx.view(Rx.size(0), 1, Rx.size(1))
        # FC Block
        Rx = self.fc(Rx)  # Shape: [Batch size, 1, 2N^2])
        # Reshape Output shape: [Batch size, 2N, N]
        Rx_view = Rx.view(self.BATCH_SIZE, 2 * self.N, self.N)
        Rx_real = Rx_view[:, : self.N, :]  # Shape [Batch size, N, N])
        Rx_imag = Rx_view[:, self.N:, :]  # Shape [Batch size, N, N])
        Kx_tag = torch.complex(Rx_real, Rx_imag)  # Shape [Batch size, N, N])
        # Build MUSIC spectrum
        spectrum = self.pre_MUSIC(Kx_tag)  # Shape [Batch size, 361(grid_size)])
        # Apply peak detection using FC block #2
        y = self.ReLU(self.fc1(spectrum))  # Shape [Batch size, 361(grid_size)])
        y = self.ReLU(self.fc2(y))  # Shape [Batch size, 2N])
        y = self.ReLU(self.fc2(y))  # Shape [Batch size, 2N)
        # Find doa
        DOA = self.fc3(y)  # Shape [Batch size, M)
        return DOA


class DeepCNN(nn.Module):
    """DeepCNN is a convolutional neural network model for DoA  estimation.

    Args:
        N (int): Input dimension size.
        grid_size (int): Size of the output grid.

    Attributes:
        N (int): Input dimension size.
        grid_size (int): Size of the output grid.
        conv1 (nn.Conv2d): Convolutional layer 1.
        conv2 (nn.Conv2d): Convolutional layer 2.
        fc1 (nn.Linear): Fully connected layer 1.
        BatchNorm (nn.BatchNorm2d): Batch normalization layer.
        fc2 (nn.Linear): Fully connected layer 2.
        fc3 (nn.Linear): Fully connected layer 3.
        fc4 (nn.Linear): Fully connected layer 4.
        DropOut (nn.Dropout): Dropout layer.
        Sigmoid (nn.Sigmoid): Sigmoid activation function.
        ReLU (nn.ReLU): Rectified Linear Unit activation function.

    Methods:
        forward(X: torch.Tensor): Performs the forward pass of the DeepCNN model.
    """

    def __init__(self, N, grid_size):
        ## input dim (N, T)
        super(DeepCNN, self).__init__()
        self.N = N
        self.grid_size = grid_size
        self.conv1 = nn.Conv2d(3, 256, kernel_size=3)
        self.conv2 = nn.Conv2d(256, 256, kernel_size=2)
        self.fc1 = nn.Linear(256 * (self.N - 5) * (self.N - 5), 4096)
        self.BatchNorm = nn.BatchNorm2d(256)
        self.fc2 = nn.Linear(4096, 2048)
        self.fc3 = nn.Linear(2048, 1024)
        self.fc4 = nn.Linear(1024, self.grid_size)
        self.DropOut = nn.Dropout(0.3)
        self.Sigmoid = nn.Sigmoid()
        self.ReLU = nn.ReLU()

    def forward(self, X):
        # X shape == [Batch size, N, N, 3]
        X = X.view(X.size(0), X.size(3), X.size(2), X.size(1))  # [Batch size, 3, N, N]
        ## Architecture flow ##
        # CNN block #1: 3xNxN-->256x(N-2)x(N-2)
        X = self.conv1(X)
        X = self.ReLU(X)
        # CNN block #2: 256x(N-2)x(N-2)-->256x(N-3)x(N-3)
        X = self.conv2(X)
        X = self.ReLU(X)
        # CNN block #3: 256x(N-3)x(N-3)-->256x(N-4)x(N-4)
        X = self.conv2(X)
        X = self.ReLU(X)
        # CNN block #4: 256x(N-4)x(N-4)-->256x(N-5)x(N-5)
        X = self.conv2(X)
        X = self.ReLU(X)
        # FC BLOCK
        # Reshape Output shape: [Batch size, 256 * (self.N - 5) * (self.N - 5)]
        X = X.view(X.size(0), -1)
        X = self.DropOut(self.ReLU(self.fc1(X)))  # [Batch size, 4096]
        X = self.DropOut(self.ReLU(self.fc2(X)))  # [Batch size, 2048]
        X = self.DropOut(self.ReLU(self.fc3(X)))  # [Batch size, 1024]
        X = self.fc4(X)  # [Batch size, grid_size]
        X = self.Sigmoid(X)
        return X


def root_music(Rz: torch.Tensor, M: int, batch_size: int):
    """Implementation of the model-based Root-MUSIC algorithm, support Pytorch, intended for
        MB-DL models. the model sets for nominal and ideal condition (Narrow-band, ULA, non-coherent)
        as it accepts the surrogate covariance matrix.
        it is equivalent tosrc.methods: RootMUSIC.narrowband() method.

    Args:
    -----
        Rz (torch.Tensor): Focused covariance matrix
        M (int): Number of sources
        batch_size: the number of batches

    Returns:
    --------
        doa_batches (torch.Tensor): The predicted doa, over all batches.
        doa_all_batches (torch.Tensor): All doa predicted, given all roots, over all batches.
        roots_to_return (torch.Tensor): The unsorted roots.
    """

    dist = 0.5
    f = 1
    doa_batches = []
    doa_all_batches = []
    Bs_Rz = Rz
    for iter in range(batch_size):
        R = Bs_Rz[iter]
        # Extract eigenvalues and eigenvectors using EVD
        eigenvalues, eigenvectors = torch.linalg.eig(R)
        # Assign noise subspace as the eigenvectors associated with M greatest eigenvalues
        Un = eigenvectors[:, torch.argsort(torch.abs(eigenvalues)).flip(0)][:, M:]
        # Generate hermitian noise subspace matrix
        F = torch.matmul(Un, torch.t(torch.conj(Un)))
        # Calculates the sum of F matrix diagonals
        diag_sum = sum_of_diags_torch(F)
        # Calculates the roots of the polynomial defined by F matrix diagonals
        roots = find_roots_torch(diag_sum)
        # Calculate the phase component of the roots
        roots_angels_all = torch.angle(roots)
        # Calculate doa
        doa_pred_all = torch.arcsin((1 / (2 * np.pi * dist * f)) * roots_angels_all)
        doa_all_batches.append(doa_pred_all)
        roots_to_return = roots
        # Take only roots which inside the unit circle
        roots = roots[
            sorted(range(roots.shape[0]), key=lambda k: abs(abs(roots[k]) - 1))
        ]
        mask = (torch.abs(roots) - 1) < 0
        roots = roots[mask][:M]
        # Calculate the phase component of the roots
        roots_angels = torch.angle(roots)
        # Calculate doa
        doa_pred = torch.arcsin((1 / (2 * np.pi * dist * f)) * roots_angels)
        doa_batches.append(doa_pred)

    return (
        torch.stack(doa_batches, dim=0),
        torch.stack(doa_all_batches, dim=0),
        roots_to_return,
    )


def esprit(Rz: torch.Tensor, M: int, batch_size: int):
    """Implementation of the model-based Esprit algorithm, support Pytorch, intended for
        MB-DL models. the model sets for nominal and ideal condition (Narrow-band, ULA, non-coherent)
        as it accepts the surrogate covariance matrix.
        it is equivalent to src.methods: RootMUSIC.narrowband() method.

    Args:
    -----
        Rz (torch.Tensor): Focused covariance matrix
        M (int): Number of sources
        batch_size: the number of batches

    Returns:
    --------
        doa_batches (torch.Tensor): The predicted doa, over all batches.
    """

    doa_batches = []

    Bs_Rz = Rz
    for iter in range(batch_size):
        R = Bs_Rz[iter]
        # Extract eigenvalues and eigenvectors using EVD
        eigenvalues, eigenvectors = torch.linalg.eig(R)

        # Get signal subspace
        Us = eigenvectors[:, torch.argsort(torch.abs(eigenvalues)).flip(0)][:, :M]
        # Separate the signal subspace into 2 overlapping subspaces
        Us_upper, Us_lower = (
            Us[0: R.shape[0] - 1],
            Us[1: R.shape[0]],
        )
        # Generate Phi matrix
        phi = torch.linalg.pinv(Us_upper) @ Us_lower
        # Find eigenvalues and eigenvectors (EVD) of Phi
        phi_eigenvalues, _ = torch.linalg.eig(phi)
        # Calculate the phase component of the roots
        eigenvalues_angels = torch.angle(phi_eigenvalues)
        # Calculate the DoA out of the phase component
        doa_predictions = -1 * torch.arcsin((1 / np.pi) * eigenvalues_angels)
        doa_batches.append(doa_predictions)

    return torch.stack(doa_batches, dim=0)


def music_2d(Rz: torch.Tensor, number_of_sources: int, search_grid: torch.Tensor, theta_range, distance_range,
             is_soft: bool = True) -> tuple:
    """

        Args:
            Rz:
            number_of_sources:

        Returns:

        """
    torch.autograd.set_detect_anomaly(True)

    # using for loops
    # music_spectrum = torch.zeros((Rz.shape[0], len(theta_range), len(distance_range)), dtype=torch.complex64)
    # for batch in range(Rz.shape[0]):
    #     R = Rz[batch]
    #     eigenvalues, eigenvectors = torch.linalg.eig(R)
    #     sorted_indxs = torch.argsort(torch.abs(eigenvalues), descending=True)
    #     Un = eigenvectors[sorted_indxs][:, number_of_sources].unsqueeze(1)
    #     for t, theta in enumerate(theta_range):
    #         for d, distance in enumerate(distance_range):
    #             A = search_grid[:, t, d]
    #             core_equiation = A.conj().T @ Un @ Un.conj().T @ A
    #             music_spectrum[batch, t, d] = 1 / torch.real(core_equiation)

    # using einsum
    # Extract eigenvalues and eigenvectors using EVD
    eigenvalues, eigenvectors = torch.linalg.eig(Rz)
    # Assign noise subspace as the eigenvectors associated with the M-greatest eigenvalues
    sorted_indxs = torch.argsort(torch.real(eigenvalues), descending=True)
    # Un = torch.zeros(Rz.shape[0], Rz.shape[1], Rz.shape[2] - number_of_sources).type(torch.complex64)
    music_spectrum = torch.zeros(Rz.shape[0], len(theta_range), len(distance_range))
    for batch in range(Rz.shape[0]):
        Un = eigenvectors[batch][sorted_indxs[batch]][:, number_of_sources:]
        var_1 = torch.transpose(search_grid.conj(), 0, 2) @ Un
        inverse_spectrum = torch.norm(torch.transpose(var_1, 0, 1), dim=2)
        music_spectrum[batch] = 1 / inverse_spectrum
    # var_1 = torch.einsum("dtn, bnm -> bdtm", torch.transpose(search_grid.conj(), 0, 2), Un)
    # var_2 = torch.transpose(var_1.conj(), -3, -1)
    # inverse_spectrum = torch.einsum("bijk, bkji -> bji", var_1, var_2)
    # if not inverse_spectrum.isreal().all():
    #     raise ValueError("Music spectrum must to be real!")
    # music_spectrum = 1 / torch.real(inverse_spectrum)
    if is_soft:
        doa, distance = maskpeaks(music_spectrum, number_of_sources, theta_range, distance_range)
    else:
        doa, distance = find_spectrum_peaks(music_spectrum, number_of_sources, theta_range, distance_range)
    torch.autograd.set_detect_anomaly(False)

    return torch.Tensor(doa), torch.Tensor(distance)


def find_spectrum_peaks(music_spectrum, number_of_sources, theta_range, distance_range):
    music_spectrum = music_spectrum.detach().numpy().squeeze()
    # Flatten the spectrum
    spectrum_flatten = music_spectrum.flatten()
    # Find spectrum peaks
    peaks = list(sc.signal.find_peaks(spectrum_flatten)[0])
    # Sort the peak by their amplitude
    peaks.sort(key=lambda x: spectrum_flatten[x], reverse=True)
    # convert the peaks to 2d indices
    original_idx = np.unravel_index(peaks, music_spectrum.shape)
    predict_theta = theta_range[original_idx[0]][0:number_of_sources]
    predict_dist = distance_range[original_idx[1]][0:number_of_sources]

    return predict_theta, predict_dist


def maskpeaks(spectrum: torch.Tensor, number_of_sources: int, theta_range: torch.Tensor,
              distance_range: torch.Tensor) -> tuple:
    """

        Args:
            batch_size:
            spectrum:
            number_of_sources:

        Returns:

        """
    _, top_indxs = torch.topk(spectrum.view(spectrum.shape[0], -1), number_of_sources, dim=1)
    max_row = torch.div(top_indxs, spectrum.shape[2], rounding_mode="floor")
    max_col = torch.fmod(top_indxs, spectrum.shape[2]).int()

    soft_row = torch.zeros(spectrum.shape[0], number_of_sources, dtype=torch.float32).to(device)
    soft_col = torch.zeros(spectrum.shape[0], number_of_sources, dtype=torch.float32).to(device)
    cell_size = 5
    for i, (max_r, max_c) in enumerate(zip(max_row, max_col)):
        max_row_cell_idx = (max_r \
                            - cell_size \
                            + torch.arange(2 * cell_size + 1, dtype=torch.long, device=device).unsqueeze(1).expand(
                    -1, max_r.shape[0])).to(device)
        max_row_cell_idx = max_row_cell_idx[max_row_cell_idx >= 0]
        max_row_cell_idx = max_row_cell_idx[max_row_cell_idx < spectrum.shape[1]].view(-1, 1)


        max_col_cell_idx = (max_c \
                            - cell_size \
                            + torch.arange(2 * cell_size + 1, dtype=torch.long, device=device).unsqueeze(1).expand(
                    -1, max_c.shape[0])).to(device)
        max_col_cell_idx = max_col_cell_idx[max_col_cell_idx >= 0]
        max_col_cell_idx = max_col_cell_idx[max_col_cell_idx < spectrum.shape[2]].view(1, -1)
        for k in range(number_of_sources):
            # max_row_cell_idx_k = torch.fmod(max_row_cell_idx[:, k].view(-1, 1), spectrum.shape[1])
            # max_col_cell_idx_k = torch.fmod(max_col_cell_idx[:, k].view(1, -1), spectrum.shape[2])
            max_row_cell_idx_k = max_row_cell_idx[:, k].view(-1, 1)
            max_col_cell_idx_k = max_col_cell_idx[k, :].view(1, -1)

            metrix_thr = spectrum[i, max_row_cell_idx_k, max_col_cell_idx_k]# / torch.max(
                # spectrum[i, max_row_cell_idx_k, max_col_cell_idx_k])
            soft_max = torch.softmax(metrix_thr.view(1, -1), dim=1).reshape(metrix_thr.shape)

            soft_row[i, k] = theta_range[max_row_cell_idx_k].T @ torch.sum(soft_max, dim=1)
            soft_col[i, k] = distance_range[max_col_cell_idx_k] @ torch.sum(soft_max, dim=0)

    return soft_row, soft_col
